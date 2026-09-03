import { BASE, getJSON } from "../../lib/api";

export type ModelLabPolicyAuthority = {
  policyId: string;
  version: number;
  checksum: string;
  status: string;
};

export type ModelLabFold = {
  foldNumber: number;
  trainingStart: string;
  trainingEnd: string;
  validationStart: string;
  validationEnd: string;
  trainRows: number;
  validationRows: number;
};

export type ModelLabFeatureSet = {
  featureSetId: string;
  key: string;
  name: string;
  version: number;
  featureCount: number;
  orderedFeatures: string[];
  status: string;
  checksum: string;
  workflowRole?: string;
  executionStatus?: string;
  executable?: boolean;
  defaultEligible?: boolean;
  blockingFeatures?: ModelEligibilityDecision[];
  reviewRequiredFeatures?: ModelEligibilityDecision[];
  overrideEligible?: boolean;
};

export type ModelEligibilityDecision = {
  name: string;
  classification: string;
  status: string;
  reason: string;
  missingPercentDevelopment: number;
  overrideAllowed: boolean;
};

export type FullEligibleFeatureUniverse = {
  featureSetId: string;
  featureSetKey: "FULL_ELIGIBLE_MODELING_SET";
  name: string;
  version: number;
  status: string;
  checksum: string;
  featureCount: number;
  orderedFeatures: string[];
  exclusions: ModelEligibilityDecision[];
  reconciliation: {
    physicalCandidateCount: number;
    eligiblePredictorCount: number;
    excludedPredictorCount: number;
    sourceUnavailable: number;
    missingness: number;
    pitLeakage: number;
    identity: number;
    computationFailure: number;
    other: number;
  };
  simulatorGeneratedStateFeatures: string[];
  finalOotLocked: true;
  finalOotTargetAccessed: false;
};

export type ModelAlgorithm = {
  id: string;
  label: string;
  family: string;
  available: boolean;
  automaticBundleEligible: boolean;
  status: string;
  unavailableReason?: string | null;
  supportedTuningModes: ("FIXED" | "GRID" | "RANDOM")[];
  defaultTuningMode: "FIXED" | "GRID" | "RANDOM";
  defaultGridPreset: "COMPACT" | "FULL" | "CUSTOM";
  fixedHyperparameters: Record<string, unknown>;
  compactGrid: Record<string, unknown>[];
  fullGrid: Record<string, unknown[]>;
  allowedHyperparameters: string[];
  computeIntensity: string;
  probabilityTreatment: string;
  interpretabilitySupport: string[];
  computeGuard: ModelComputeGuard;
  executionResources?: ModelExecutionResources;
};

export type ModelComputeGuard = {
  fullEligibleFeatureSetExecution?: boolean;
  replacementAlgorithmId?: string;
  reasonCode?: string;
  reason?: string;
  [key: string]: unknown;
};

export type ModelExecutionResources = {
  computeIntensity?: string;
  exclusiveCandidate?: boolean;
  nativeWorkers?: number;
  maximumConcurrentSameAlgorithm?: number;
  nestedOversubscriptionProhibited?: boolean;
  [key: string]: unknown;
};

export type ModelCatalog = {
  algorithms: ModelAlgorithm[];
  families: { id: string; label: string; algorithms: string[] }[];
  tuning: {
    modes: ("FIXED" | "GRID" | "RANDOM")[];
    gridPresets: ("COMPACT" | "FULL" | "CUSTOM")[];
    warningFitThreshold: number;
    hardFitLimit: number;
    foldCount: number;
  };
  anomalyAnalytics: { status: string; algorithms: string[]; purposes: string[] };
  interpretabilityRoadmap: Record<string, unknown>;
};

export type ModelLabFamily = {
  id: string;
  label: string;
  available: boolean;
  status: string;
  unavailableReason?: string | null;
};

export type ModelLabCandidatePlan = {
  candidateKey: string;
  modelFamily: string;
  featureSetId: string | null;
  featureSetName: string;
  status: string;
};

export type ModelLabCandidateResult = {
  candidateId: string;
  modelFamily: string;
  featureSetId: string | null;
  featureSetName: string;
  status: string;
  foldsCompleted: number;
  meanOofLogLoss: number | null;
  summedBrier: number | null;
  ece: number | null;
  macroF1: number | null;
  accuracyDiagnostic: number | null;
  rareClassStability: string | number | null;
  foldStability: number | null;
  modelComplexity: string | null;
  classCalibrationDiagnostics: unknown[];
  runtimeMs: number | null;
  errorReason: string | null;
  hyperparameters?: Record<string, unknown>;
  featureCount?: number;
  interpretabilityEvidence?: Record<string, unknown> | null;
  evaluationEvidence?: Record<string, unknown> | null;
};

export type ModelLabRun = {
  runId: string;
  status: string;
  createdAt?: string;
  identity: {
    projectId: string;
    goldDatasetId: string;
    goldManifestSha: string;
    splitContractId: string;
    outlierPolicyId: string;
    missingPolicyId: string;
    featureSetIds: string[];
    targetOrder: string[];
    seed?: number;
    featureUniverseId?: string;
    featureUniverseChecksum?: string;
  };
  candidates: ModelLabCandidateResult[];
  autoPromoted: false;
  promotionStatus: "NOT_PROMOTED";
  providerCalls: 0;
  legacyGlobalMatrixUsed: false;
  finalOotAccessed: false;
  finalOotTargetsMaterialized: false;
  population: { finalOotTargetAccessed: false; finalOotScored: false };
};

export type ProjectModelLabSummary = {
  authority: {
    projectId: string;
    projectName: string;
    sourceDatasetId: string;
    datasetVersionId: string;
    goldDatasetId: string;
    goldManifestSha: string;
    contextualDatasetId: string;
    contextualManifestSha: string;
    authorityKey: string;
    legacyGlobalMatrixUsed?: boolean;
  };
  population: {
    scope: "DEVELOPMENT_ONLY";
    developmentRows: number;
    startDate: string;
    endDate: string;
    finalOotRows: number;
    finalOotStartDate: string;
    finalOotEndDate: string;
    finalOotLocked: true;
    finalOotTargetsMaterialized: false;
  };
  target: { name: string; orderedClasses: string[] };
  policies: { outlier: ModelLabPolicyAuthority; missing: ModelLabPolicyAuthority };
  split: {
    splitContractId: string;
    version: number;
    checksum: string;
    status: string;
    foldCount: number;
    folds: ModelLabFold[];
  };
  featureSets: ModelLabFeatureSet[];
  featureUniverse: FullEligibleFeatureUniverse;
  featureUniverseChoices: {
    id: string;
    key: string;
    label: string;
    featureCount: number | null;
    status: string;
    default: boolean;
    executable: boolean;
  }[];
  modelFamilies: ModelLabFamily[];
  modelCatalog: ModelCatalog;
  candidateMatrix: ModelLabCandidatePlan[];
  readiness: { ready: boolean; blockers: string[] };
  latestRun: ModelLabRun | null;
  historicalEvidence: {
    label: string;
    immutable: boolean;
    runCount: number;
    runs: ModelLabRun[];
    failedCandidatesRemainVisible: boolean;
  };
  audit?: {
    legacyGlobalMatrixUsed: boolean;
    base22FallbackAvailable: boolean;
    globalMatrixFallbackAvailable: boolean;
    finalOotTargetAccessed: boolean;
    finalOotUsedForSelection: boolean;
    providerCalls: number;
    autoPromotion: boolean;
  };
};

export type ModelExperimentDraft = {
  algorithmId: string;
  featureUniverseId: string;
  tuningMode: "FIXED" | "GRID" | "RANDOM";
  gridPreset: "COMPACT" | "FULL" | "CUSTOM";
  fixedHyperparameters?: Record<string, unknown>;
  customGrid?: Record<string, unknown[]>;
  compactGrid?: Record<string, unknown>[];
  randomIterations?: number;
  orderedFeatures?: string[];
  eligibilityOverrideRationale?: string;
  prospectiveSemanticCompatibilityAcknowledged?: boolean;
  foldLocalTreatmentAcknowledged?: boolean;
  seed?: number;
  parentCandidateFingerprint?: string;
  refinementPlanId?: string;
};

export type ModelDevelopmentPlan = {
  planId: string;
  checksum: string;
  totalExperiments: number;
  totalConfigurations: number;
  totalFits: number;
  requiresAcknowledgement: boolean;
  hardFitLimit: number;
  executable: boolean;
  executionBlocker: string | null;
  finalOotLocked: true;
  finalOotTargetAccessed: false;
  batchName?: string;
  parallelism: {
    mode: "AUTO" | "MANUAL";
    requested: "AUTO" | number;
    effectiveCandidateWorkers: number;
    maximumCandidateWorkers: number;
    logicalCpuCount: number;
    physicalMemoryGiB: number | null;
    highMemoryCandidatePresent: boolean;
    estimatorNativeWorkers: number;
    maximumEstimatorNativeWorkers: number;
    exclusiveCandidateWorkers: number;
    schedulingPolicy: string;
    nestedOversubscriptionProhibited: true;
  };
  experiments: Array<{
    experimentId: string;
    modelFamily: string;
    algorithmId: string;
    algorithmLabel: string;
    featureUniverseId: string | null;
    featureUniverseName: string;
    featureUniverseChecksum: string | null;
    featureCount: number;
    computeIntensity: string;
    executionResources: ModelExecutionResources;
    tuning: {
      tuningMode: string;
      gridPreset: string;
      configurationCount: number;
      foldCount: number;
      totalFits: number;
      requiresAcknowledgement: boolean;
      exceedsHardLimit: boolean;
    };
  }>;
};

export type ModelDevelopmentJobStatus =
  | "QUEUED"
  | "RUNNING"
  | "CANCEL_REQUESTED"
  | "COMPLETE"
  | "PARTIAL"
  | "FAILED"
  | "INTERRUPTED"
  | "CANCELLED"
  | "CANCELLED_PARTIAL";

export type ModelDevelopmentJob = {
  jobId: string;
  projectId: string;
  status: ModelDevelopmentJobStatus;
  startedAt: string | null;
  completedAt: string | null;
  plan: ModelDevelopmentPlan;
  progress: {
    state: string;
    completedFits: number;
    failedFits: number;
    cancelledFits?: number;
    pendingFits?: number;
    unstartedFits?: number;
    unresolvedFits?: number;
    totalFits: number;
    currentAlgorithm?: string;
    currentFeatureUniverse?: string;
    currentConfiguration?: number;
    currentHyperparameters?: Record<string, unknown>;
    configurationCount?: number;
    currentFold?: number;
    foldCount?: number;
    elapsedSeconds: number;
    estimatedRemainingSeconds: number | null;
    message: string;
    failures?: unknown[];
    completedConfigurations?: number;
    failedConfigurations?: number;
    cancelledConfigurations?: number;
    remainingFits?: number;
    cancellationPendingFits?: number;
    drainingActiveCandidates?: number;
    runtimeAdmission?: {
      plannedCandidateWorkers: number;
      effectiveCandidateWorkers: number;
      availableMemoryGiBAtStart: number | null;
      admissionPolicy: string;
    };
    parallelWorkers?: number;
    activeCandidates?: Array<{
      taskId: string;
      algorithm: string;
      algorithmLabel: string;
      featureUniverse: string;
      configuration: number;
      configurationCount: number;
      hyperparameters: Record<string, unknown>;
      fold: number;
      foldCount: number;
      status: string;
      elapsedSeconds: number;
      executionResources?: ModelExecutionResources;
    }>;
    interruptedCandidates?: Array<{
      taskId?: string;
      algorithm?: string;
      algorithmLabel?: string;
      featureUniverse?: string;
      configuration?: number;
      configurationCount?: number;
      hyperparameters?: Record<string, unknown>;
      fold?: number;
      foldCount?: number;
      status?: string;
      elapsedSeconds?: number;
      executionResources?: ModelExecutionResources;
    }>;
    completedCandidateReceipts?: Array<{
      candidateId: string;
      candidateReceiptSha256: string;
      status: string;
    }>;
    cancelUnstartedRequested?: boolean;
    cancelRequestedAt?: string | null;
  };
  artifacts: {
    runId?: string;
    runReceiptSha256?: string;
    promotionStatus?: string;
    coordinatorProcessId?: number;
    completedCandidateReceipts?: Array<{
      candidateId: string;
      candidateReceiptSha256: string;
      status: string;
    }>;
  };
  error: { code?: string; message?: string };
};

export type CandidateEvidenceSource =
  | "CURRENT_BATCH"
  | "HISTORICAL_BASELINE"
  | "INCREMENTAL_CURRENT_EVIDENCE";

export type FinalistEvaluationBatch = Extract<
  CandidateEvidenceSource,
  "CURRENT_BATCH" | "HISTORICAL_BASELINE"
>;

export type CandidateAttempt = {
  attemptId: string;
  candidateFingerprint: string;
  runId: string;
  runReceiptSha256: string;
  receiptSchemaVersion: string;
  evidenceSource: CandidateEvidenceSource;
  createdAt: string;
  status: string;
  modelFamily: string;
  featureSetId: string | null;
  featureSetName: string;
  featureCount: number;
  hyperparameters: Record<string, unknown>;
  tuningMode: string;
  gridPreset: string;
  seed: number;
  foldsCompleted: number;
  meanOofLogLoss: number | null;
  foldStandardDeviation: number | null;
  summedBrier: number | null;
  ece: number | null;
  macroF1: number | null;
  accuracy: number | null;
  runtimeMs: number | null;
  errorCode?: string | null;
  errorReason?: string | null;
  folds: Array<Record<string, any>>;
  classCalibration: Array<Record<string, any>>;
  modelComplexity?: Record<string, any> | string | null;
  interpretabilityEvidence?: Record<string, any> | null;
  evaluationEvidence?: Record<string, any> | null;
  orderedFeatures?: string[];
};

export type CandidateGroup = {
  candidateFingerprint: string;
  modelFamily: string;
  featureSetId: string | null;
  featureSetName: string;
  featureCount: number;
  hyperparameters: Record<string, unknown>;
  tuningMode: string;
  gridPreset: string;
  status: string;
  attemptCount: number;
  completedAttemptCount: number;
  failedAttemptCount: number;
  reproducibilityStatus: string;
  rankingEligible: boolean;
  evidenceSources: CandidateEvidenceSource[];
  meanOofLogLoss: number | null;
  foldStandardDeviation: number | null;
  summedBrier: number | null;
  ece: number | null;
  macroF1: number | null;
  accuracy: number | null;
  runtimeMs: number | null;
  foldsCompleted: number;
  immutableEvidenceIdentity: string;
  representativeAttemptId: string;
  attempts: CandidateAttempt[];
  rank: number | null;
  developmentLabel: string;
  finalist: boolean;
};

export type FinalistCandidateSelection = {
  candidateFingerprint: string;
  evidenceSource: FinalistEvaluationBatch;
  representativeAttemptId: string;
  immutableEvidenceIdentity: string;
  attemptEvidence: Array<{
    attemptId: string;
    runId: string;
    runReceiptSha256: string;
  }>;
};

export type SaveProjectCandidateFinalistsPayload = {
  candidateFingerprints: string[];
  candidateSelections: FinalistCandidateSelection[];
  rationale: string;
  evaluationBatch: FinalistEvaluationBatch;
};

export type ProjectCandidateEvaluation = {
  ok: true;
  schemaVersion: string;
  authority: {
    projectId: string;
    projectName: string;
    goldDatasetId: string;
    goldManifestSha: string;
    authorityKey: string;
    splitContractId: string;
    splitChecksum: string;
    outlierPolicyId: string;
    missingPolicyId: string;
    targetOrder: string[];
    legacyGlobalMatrixUsed: false;
    base22FallbackAvailable: false;
  };
  population: {
    scope: "DEVELOPMENT_ONLY";
    developmentRows: number;
    startDate: string;
    endDate: string;
    foldCount: 5;
    finalOotRows: number;
    finalOotStartDate: string;
    finalOotEndDate: string;
    finalOotLocked: true;
    finalOotTargetAccessed: false;
    finalOotScored: false;
  };
  activity: {
    immutableRunReceipts: number;
    historicalRunReceipts: number;
    currentBatchReceipts: number;
    uniqueCandidateSpecifications: number;
    attempts: number;
    completedAttempts: number;
    failedAttempts: number;
    modelFitsDisplayedAsProjectEvidence: number;
    newFitsOnPageLoad: 0;
    providerCalls: 0;
    modelsPromoted: 0;
    incrementalVerifiedCandidateReceipts?: number;
    incrementalHeldClosedReceipts?: number;
  };
  currentBatches: CandidateGroup[];
  incrementalCurrentEvidence?: {
    status: string;
    jobId?: string | null;
    planId?: string | null;
    verifiedCandidateReceipts?: number;
    heldClosedReceipts?: number;
    candidateGroups: CandidateGroup[];
    diagnostics?: Array<{
      code: string;
      message: string;
      candidateReceiptSha256?: string;
    }>;
    rankingEligible: false;
    finalistSelectionEligible: false;
  };
  historicalEvidence: {
    collapsedByDefault: boolean;
    banner: string;
    candidates: CandidateGroup[];
  };
  candidateGroups: CandidateGroup[];
  finalists: Array<Record<string, any>>;
  refinements: Array<Record<string, any>>;
  analysisRequests: Array<Record<string, any>>;
  selectionMetric: string;
  promotionStatus: "NOT_PROMOTED";
  finalOotAccessed: false;
};

export type ProjectDownstreamFinalist = {
  candidateFingerprint: string;
  modelFamily: string;
  featureSetId?: string | null;
  featureSetName: string;
  featureCount: number;
  evidenceSource: CandidateEvidenceSource;
  attemptId?: string;
  runId?: string;
  runReceiptSha256?: string;
  representativeAttemptId?: string;
  immutableEvidenceIdentity?: string;
  meanOofLogLoss: number | null;
  foldStandardDeviation?: number | null;
  summedBrier: number | null;
  ece: number | null;
  macroF1?: number | null;
  accuracy?: number | null;
  foldsCompleted: number;
  classCalibration: Array<{
    class: string;
    support: number;
    meanPredictedProbability: number;
    observedRate: number;
    absoluteCalibrationError: number;
    oneVsRestBrier?: number | null;
  }>;
  reloadableArtifactSha256?: string | null;
  reloadableArtifactAvailable?: boolean;
  rowLevelOofArtifactAvailable?: boolean;
  evaluationEvidence?: {
    status?: string;
    scope?: string;
    reloadableArtifactSha256?: string | null;
    reloadableArtifactStatus?: string;
    finalOotTargetAccessed?: false;
    [key: string]: unknown;
  } | null;
};

export type ProjectDownstreamDecision = {
  decisionId?: string;
  calibrationDecisionId?: string;
  gameEvaluationDecisionId?: string;
  selectionId?: string;
  selectionDecisionId?: string;
  registryEntryId?: string;
  candidateFingerprint?: string;
  finalistSelectionId?: string;
  disposition?: string;
  decision?: string;
  status?: string;
  rationale?: string;
  createdAt?: string;
  checksum?: string;
  receiptSha256?: string;
  authorityStatus?: "CURRENT" | "SUPERSEDED";
  modelStatus?: string;
  exportStatus?: string;
  deploymentStatus?: string;
  [key: string]: unknown;
};

export type ProjectStage3Downstream = {
  ok: true;
  schemaVersion?: string;
  authority: {
    projectId: string;
    projectName?: string;
    goldDatasetId: string;
    goldManifestSha: string;
    authorityKey?: string;
    splitContractId?: string;
    finalistSelectionId?: string | null;
    targetOrder?: string[];
    legacyGlobalMatrixUsed: false;
    base22FallbackAvailable?: boolean;
  };
  population: {
    scope: "DEVELOPMENT_ONLY";
    developmentRows: number;
    startDate: string;
    endDate: string;
    finalOotRows: number;
    finalOotStartDate: string;
    finalOotEndDate: string;
    finalOotLocked: true;
    finalOotTargetAccessed: false;
    finalOotScored: false;
  };
  finalists: ProjectDownstreamFinalist[];
  historicalBenchmark: {
    label?: string;
    candidateFingerprint?: string;
    modelFamily?: string;
    featureSetName?: string;
    meanOofLogLoss: number | null;
    evidenceSource?: string;
    [key: string]: unknown;
  } | null;
  calibrationDecisions: ProjectDownstreamDecision[];
  gameEvaluationDecisions: ProjectDownstreamDecision[];
  selectionDecisions: ProjectDownstreamDecision[];
  registryEntries: ProjectDownstreamDecision[];
  gates: {
    calibrationReady: boolean;
    calibrationDecisionCurrent: boolean;
    gameEvaluationReady: boolean;
    gameEvaluationDecisionCurrent: boolean;
    challengerDecisionReady: boolean;
    challengerDecisionCurrent: boolean;
    registryHandoffReady: boolean;
    registryHandoffCurrent: boolean;
  };
  activity: {
    providerCalls?: number;
    modelsPromoted?: number;
    newFitsOnPageLoad?: number;
    calibrationFits?: number;
    simulationRuns?: number;
    finalOotRowsAccessed?: number;
    modelsExported?: number;
    finalOotTargetAccessed?: boolean;
    finalOotScored?: boolean;
    [key: string]: unknown;
  };
};

type SummaryEnvelope = { ok: true } & ProjectModelLabSummary;
type RunEnvelope = { ok: true; run: ModelLabRun };
type RunsEnvelope = { ok: true; runs: ModelLabRun[] };
type PlanEnvelope = { ok: true; plan: ModelDevelopmentPlan };
type JobEnvelope = { ok: true; job: ModelDevelopmentJob };
type JobsEnvelope = { ok: true; jobs: ModelDevelopmentJob[] };

const prefix = (projectId: string) =>
  `/projects/${encodeURIComponent(projectId)}/sports/stage3-model-laboratory`;

const CURRENT_PROJECT_ID = "asp-mtddc6pw";
const CURRENT_GOLD_ID = "gold-table:gold_mlb_current_pa_v1";
const CURRENT_GOLD_MANIFEST = "67de02ce19738b29953341151640fb69244b764b0e532b687ab6bacedbb3f758";
const CURRENT_DEVELOPMENT = { rows: 683_662, start: "2023-03-30", end: "2026-08-13" } as const;
const CURRENT_FINAL_OOT = { rows: 14_067, start: "2026-08-14", end: "2026-08-27" } as const;
const CURRENT_TARGET_ORDER = ["STRIKEOUT", "WALK_HBP_CI", "HOME_RUN", "SINGLE", "DOUBLE", "TRIPLE", "BIP_OUT", "OTHER_REACH"] as const;
const CURRENT_FEATURE_SET_IDS = [
  "stage3-feature-set-9e8ade8098814fc08d4bfd63e7c60a4f",
  "stage3-feature-set-f39a3891c2684d2b95361597a03c19de",
  "stage3-feature-set-d7f38d8b7bc640f7853c1beffb63f9f6",
] as const;
const CURRENT_SPLIT_ID = "stage3-split-contract-ae8cd433f1b44e528bb82e81ae68fd6b";
const CURRENT_OUTLIER_ID = "stage3-outlier-policy-facf3b3cb90348e68fd349d14733d87a";
const CURRENT_MISSING_ID = "stage3-imputation-policy-75a1080b57b14165b22ed348f11d6896";

function exactHttpError(value: any, status: number, path: string): Error {
  const detail = value?.detail;
  const code = typeof detail === "object" ? String(detail?.code || "") : "";
  const message = typeof detail === "object"
    ? String(detail?.message || "")
    : typeof detail === "string" ? detail : "";
  return new Error([code, message].filter(Boolean).join(": ") || `${path} failed: ${status}`);
}

function assertSummary(value: SummaryEnvelope, projectId: string): SummaryEnvelope {
  const currentProject = projectId === CURRENT_PROJECT_ID;
  const exactFeatureIds = value?.featureSets?.map((item) => item.featureSetId);
  const exactTargetOrder = value?.target?.orderedClasses;
  if (
    value?.ok !== true
    || value.authority?.projectId !== projectId
    || !value.authority?.authorityKey
    || !value.authority?.goldDatasetId
    || !value.authority?.goldManifestSha
    || value.population?.scope !== "DEVELOPMENT_ONLY"
    || value.population?.developmentRows <= 0
    || value.population?.finalOotLocked !== true
    || value.population?.finalOotTargetsMaterialized !== false
    || !value.split?.splitContractId
    || value.split?.status !== "REGISTERED"
    || !Array.isArray(value.featureSets)
    || !Array.isArray(value.modelFamilies)
    || !Array.isArray(value.modelCatalog?.algorithms)
    || !value.featureUniverse?.featureSetId
    || !value.featureUniverse?.checksum
    || value.featureUniverse?.finalOotLocked !== true
    || value.featureUniverse?.finalOotTargetAccessed !== false
    || value.featureUniverse?.featureCount !== value.featureUniverse?.orderedFeatures?.length
    || value.featureUniverse?.reconciliation?.physicalCandidateCount
      !== value.featureUniverse?.reconciliation?.eligiblePredictorCount
        + value.featureUniverse?.reconciliation?.excludedPredictorCount
    || !Array.isArray(value.candidateMatrix)
    || value.authority?.legacyGlobalMatrixUsed !== false
    || value.audit?.legacyGlobalMatrixUsed !== false
    || value.audit?.base22FallbackAvailable !== false
    || value.audit?.globalMatrixFallbackAvailable !== false
    || value.audit?.finalOotTargetAccessed !== false
    || value.audit?.finalOotUsedForSelection !== false
    || value.audit?.providerCalls !== 0
    || value.audit?.autoPromotion !== false
    || (currentProject && (
      value.authority.goldDatasetId !== CURRENT_GOLD_ID
      || value.authority.goldManifestSha !== CURRENT_GOLD_MANIFEST
      || value.population.developmentRows !== CURRENT_DEVELOPMENT.rows
      || value.population.startDate !== CURRENT_DEVELOPMENT.start
      || value.population.endDate !== CURRENT_DEVELOPMENT.end
      || value.population.finalOotRows !== CURRENT_FINAL_OOT.rows
      || value.population.finalOotStartDate !== CURRENT_FINAL_OOT.start
      || value.population.finalOotEndDate !== CURRENT_FINAL_OOT.end
      || value.split.splitContractId !== CURRENT_SPLIT_ID
      || value.policies.outlier.policyId !== CURRENT_OUTLIER_ID
      || value.policies.missing.policyId !== CURRENT_MISSING_ID
      || exactTargetOrder?.length !== CURRENT_TARGET_ORDER.length
      || CURRENT_TARGET_ORDER.some((target, index) => exactTargetOrder[index] !== target)
      || exactFeatureIds?.length !== CURRENT_FEATURE_SET_IDS.length
      || CURRENT_FEATURE_SET_IDS.some((id, index) => exactFeatureIds[index] !== id)
    ))
  ) {
    throw new Error("The Model Laboratory summary did not preserve the exact project-bound development authority and final-OOT lock.");
  }
  return value;
}

function finiteNumber(value: unknown): number | null {
  if (value == null || value === "") return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function normalizedCandidate(raw: any): ModelLabCandidateResult {
  const error = raw?.errorReason;
  const rare = raw?.rareClassStability;
  const complexity = raw?.modelComplexity;
  const calibration = raw?.classCalibrationDiagnostics ?? raw?.classCalibration;
  const rareSupport = finiteNumber(rare?.totalOofSupport);
  const rareBrier = finiteNumber(rare?.oneVsRestBrier);
  const transformedFeatures = finiteNumber(complexity?.transformedFeatureCount);
  const parameterCount = finiteNumber(complexity?.parameterCount);
  return {
    candidateId: String(raw?.candidateId ?? ""),
    modelFamily: String(raw?.modelFamily ?? ""),
    featureSetId: raw?.featureSetId == null ? null : String(raw.featureSetId),
    featureSetName: String(raw?.featureSetName ?? ""),
    status: String(raw?.status ?? "UNKNOWN"),
    foldsCompleted: Number(raw?.foldsCompleted ?? 0),
    meanOofLogLoss: finiteNumber(raw?.meanOofLogLoss),
    summedBrier: finiteNumber(raw?.summedBrier),
    ece: finiteNumber(raw?.ece),
    macroF1: finiteNumber(raw?.macroF1 ?? raw?.macroF1Diagnostic),
    accuracyDiagnostic: finiteNumber(raw?.accuracyDiagnostic),
    rareClassStability: rare == null ? null : typeof rare !== "object" ? String(rare) : `${rare.class ?? "rare class"} · n=${rareSupport == null ? "—" : rareSupport.toLocaleString("en-US")} · Brier ${rareBrier == null ? "—" : rareBrier.toFixed(4)}`,
    foldStability: raw?.foldStability == null ? null : finiteNumber(typeof raw.foldStability === "object" ? raw.foldStability.logLossStdDev : raw.foldStability),
    modelComplexity: complexity == null ? null : typeof complexity !== "object" ? String(complexity) : `${complexity.estimatorClass ?? "Estimator"} · ${transformedFeatures == null ? "—" : transformedFeatures.toLocaleString("en-US")} transformed · ${parameterCount == null ? "parameter count N/A" : `${parameterCount.toLocaleString("en-US")} params`}`,
    classCalibrationDiagnostics: Array.isArray(calibration) ? calibration : [],
    runtimeMs: finiteNumber(raw?.runtimeMs),
    errorReason: error == null ? null : typeof error === "string" ? error : [error?.code, error?.message].filter(Boolean).join(": ") || "Candidate failed closed.",
    hyperparameters: raw?.hyperparameters && typeof raw.hyperparameters === "object" ? raw.hyperparameters : {},
    featureCount: Number(raw?.featureCount ?? 0),
    interpretabilityEvidence: raw?.interpretabilityEvidence && typeof raw.interpretabilityEvidence === "object" ? raw.interpretabilityEvidence : null,
    evaluationEvidence: raw?.evaluationEvidence && typeof raw.evaluationEvidence === "object" ? raw.evaluationEvidence : null,
  };
}

function normalizedRun(raw: any): ModelLabRun {
  return {
    ...raw,
    candidates: (raw?.candidates ?? []).map(normalizedCandidate),
  } as ModelLabRun;
}

function normalizedSummary(raw: SummaryEnvelope): SummaryEnvelope {
  return {
    ...raw,
    split: {
      ...raw.split,
      folds: (raw.split?.folds ?? []).map((fold: any) => ({
        foldNumber: Number(fold?.foldNumber ?? 0),
        trainingStart: String(fold?.trainingStart ?? fold?.trainStart ?? ""),
        trainingEnd: String(fold?.trainingEnd ?? fold?.trainEnd ?? ""),
        validationStart: String(fold?.validationStart ?? ""),
        validationEnd: String(fold?.validationEnd ?? ""),
        trainRows: Number(fold?.trainRows ?? fold?.trainingRows ?? 0),
        validationRows: Number(fold?.validationRows ?? 0),
      })),
    },
    latestRun: raw.latestRun ? normalizedRun(raw.latestRun) : null,
    historicalEvidence: {
      ...raw.historicalEvidence,
      runs: (raw.historicalEvidence?.runs ?? []).map(normalizedRun),
    },
  };
}

function assertRun(run: ModelLabRun, summary: ProjectModelLabSummary): ModelLabRun {
  const runFeatureIds = [...new Set(run.candidates.map((item) => item.featureSetId).filter((item): item is string => Boolean(item)))].sort();
  const identityFeatureIds = [...(run.identity?.featureSetIds ?? [])].sort();
  if (
    !run?.runId
    || run.identity?.projectId !== summary.authority.projectId
    || run.identity?.goldDatasetId !== summary.authority.goldDatasetId
    || run.identity?.goldManifestSha !== summary.authority.goldManifestSha
    || run.identity?.splitContractId !== summary.split.splitContractId
    || run.identity?.outlierPolicyId !== summary.policies.outlier.policyId
    || run.identity?.missingPolicyId !== summary.policies.missing.policyId
    || run.finalOotAccessed !== false
    || run.finalOotTargetsMaterialized !== false
    || run.population?.finalOotTargetAccessed !== false
    || run.population?.finalOotScored !== false
    || run.providerCalls !== 0
    || run.legacyGlobalMatrixUsed !== false
    || run.autoPromoted !== false
    || run.promotionStatus !== "NOT_PROMOTED"
    || !Array.isArray(run.candidates)
    || run.identity?.targetOrder?.length !== summary.target.orderedClasses.length
    || summary.target.orderedClasses.some((target, index) => run.identity.targetOrder[index] !== target)
    || runFeatureIds.length !== identityFeatureIds.length
    || runFeatureIds.some((id, index) => identityFeatureIds[index] !== id)
    || run.candidates.some((item) => {
      const algorithmKnown = summary.modelCatalog.algorithms.some((algorithm) => algorithm.id === item.modelFamily);
      const featureKnown = item.featureSetId == null
        || item.featureSetId === summary.featureUniverse.featureSetId
        || item.featureSetId.startsWith("stage3-custom-modeling-subset-")
        || summary.featureSets.some((featureSet) => featureSet.featureSetId === item.featureSetId);
      return !algorithmKnown || !featureKnown;
    })
  ) {
    throw new Error("The Model Laboratory result did not echo the exact project, Gold, split, treatment-policy, final-OOT, and zero-promotion authority.");
  }
  return run;
}

export async function fetchProjectModelLabSummary(projectId: string, signal?: AbortSignal) {
  const value = await getJSON<SummaryEnvelope>(`${prefix(projectId)}/summary`, { signal, credentials: "include" });
  const safe = assertSummary(normalizedSummary(value), projectId);
  if (safe.latestRun) assertRun(safe.latestRun, safe);
  return safe;
}

export async function fetchProjectModelLabRuns(
  projectId: string,
  summary: ProjectModelLabSummary,
  signal?: AbortSignal,
) {
  const value = await getJSON<RunsEnvelope>(`${prefix(projectId)}/runs`, { signal, credentials: "include" });
  if (value?.ok !== true || !Array.isArray(value.runs)) throw new Error("The project-bound Model Laboratory run ledger was incomplete.");
  return value.runs.map((run) => assertRun(normalizedRun(run), summary));
}

function planPayload(
  summary: ProjectModelLabSummary,
  experiments: ModelExperimentDraft[],
  acknowledgeExcessiveFits = false,
  options?: { parallelWorkers?: "AUTO" | number; batchName?: string },
) {
  return {
    authorityKey: summary.authority.authorityKey,
    splitContractId: summary.split.splitContractId,
    experiments,
    seed: 20260901,
    acknowledgeExcessiveFits,
    parallelWorkers: options?.parallelWorkers ?? "AUTO",
    batchName: options?.batchName ?? "Stage 3 multi-model development batch",
  };
}

async function postJSON<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method: "POST",
    body: JSON.stringify(body),
    signal,
    credentials: "include",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
  });
  const value = await response.json().catch(() => null);
  if (!response.ok) throw exactHttpError(value, response.status, path);
  return value as T;
}

export async function planProjectModelDevelopment(
  projectId: string,
  summary: ProjectModelLabSummary,
  experiments: ModelExperimentDraft[],
  acknowledgeExcessiveFits = false,
  signal?: AbortSignal,
  options?: { parallelWorkers?: "AUTO" | number; batchName?: string },
) {
  const path = `${prefix(projectId)}/plan`;
  const value = await postJSON<PlanEnvelope>(
    path,
    planPayload(summary, experiments, acknowledgeExcessiveFits, options),
    signal,
  );
  if (value?.ok !== true || !value.plan?.planId) throw new Error("The model-development plan response was incomplete.");
  if (value.plan.finalOotLocked !== true || value.plan.finalOotTargetAccessed !== false) {
    throw new Error("The model-development plan did not preserve the final-OOT lock.");
  }
  return value.plan;
}

export async function enqueueProjectModelDevelopment(
  projectId: string,
  summary: ProjectModelLabSummary,
  experiments: ModelExperimentDraft[],
  acknowledgeExcessiveFits: boolean,
  reviewedPlan: Pick<ModelDevelopmentPlan, "planId" | "checksum">,
  signal?: AbortSignal,
  options?: { parallelWorkers?: "AUTO" | number; batchName?: string },
) {
  const path = `${prefix(projectId)}/jobs`;
  const value = await postJSON<JobEnvelope>(
    path,
    {
      ...planPayload(summary, experiments, acknowledgeExcessiveFits, options),
      expectedPlanId: reviewedPlan.planId,
      expectedPlanChecksum: reviewedPlan.checksum,
    },
    signal,
  );
  if (value?.ok !== true || !value.job?.jobId) throw new Error("The model-development job response was incomplete.");
  if (
    value.job.projectId !== projectId
    || value.job.plan?.planId !== reviewedPlan.planId
    || value.job.plan?.checksum !== reviewedPlan.checksum
    || value.job.plan?.finalOotLocked !== true
    || value.job.plan?.finalOotTargetAccessed !== false
  ) {
    throw new Error("The queued job did not bind the exact reviewed plan and final-OOT lock.");
  }
  return value.job;
}

export async function fetchProjectModelDevelopmentJobs(projectId: string, signal?: AbortSignal) {
  const value = await getJSON<JobsEnvelope>(`${prefix(projectId)}/jobs`, { signal, credentials: "include" });
  if (value?.ok !== true || !Array.isArray(value.jobs)) throw new Error("The model-development job ledger was incomplete.");
  return value.jobs;
}

export async function fetchProjectModelDevelopmentJob(
  projectId: string,
  jobId: string,
  signal?: AbortSignal,
) {
  const value = await getJSON<JobEnvelope>(`${prefix(projectId)}/jobs/${encodeURIComponent(jobId)}`, { signal, credentials: "include" });
  if (value?.ok !== true || value.job?.jobId !== jobId || value.job?.projectId !== projectId) throw new Error("The model-development job status was incomplete.");
  return value.job;
}

export async function cancelUnstartedProjectModelDevelopment(
  projectId: string,
  jobId: string,
  signal?: AbortSignal,
) {
  const path = `${prefix(projectId)}/jobs/${encodeURIComponent(jobId)}/cancel-unstarted`;
  const value = await postJSON<JobEnvelope>(path, {}, signal);
  if (
    value?.ok !== true
    || value.job?.jobId !== jobId
    || value.job?.projectId !== projectId
    || !["CANCEL_REQUESTED", "CANCELLED", "CANCELLED_PARTIAL", "COMPLETE", "PARTIAL", "FAILED", "INTERRUPTED"].includes(value.job.status)
  ) throw new Error("The cancel-unstarted acknowledgement was incomplete or did not record cancellation.");
  return value.job;
}

const evaluationPrefix = (projectId: string) =>
  `/projects/${encodeURIComponent(projectId)}/sports/stage3-candidate-evaluation`;

function assertEvaluation(value: ProjectCandidateEvaluation, projectId: string) {
  if (
    value?.ok !== true
    || value.authority?.projectId !== projectId
    || value.authority?.legacyGlobalMatrixUsed !== false
    || value.authority?.base22FallbackAvailable !== false
    || value.population?.scope !== "DEVELOPMENT_ONLY"
    || value.population?.finalOotLocked !== true
    || value.population?.finalOotTargetAccessed !== false
    || value.population?.finalOotScored !== false
    || value.activity?.newFitsOnPageLoad !== 0
    || value.activity?.providerCalls !== 0
    || value.activity?.modelsPromoted !== 0
    || value.promotionStatus !== "NOT_PROMOTED"
    || value.finalOotAccessed !== false
    || !Array.isArray(value.candidateGroups)
    || (value.incrementalCurrentEvidence != null && (
      !Array.isArray(value.incrementalCurrentEvidence.candidateGroups)
      || value.incrementalCurrentEvidence.rankingEligible !== false
      || value.incrementalCurrentEvidence.finalistSelectionEligible !== false
    ))
    || !Array.isArray(value.authority.targetOrder)
    || (projectId === CURRENT_PROJECT_ID && (
      value.authority.goldDatasetId !== CURRENT_GOLD_ID
      || value.authority.goldManifestSha !== CURRENT_GOLD_MANIFEST
      || value.population.developmentRows !== CURRENT_DEVELOPMENT.rows
      || value.population.startDate !== CURRENT_DEVELOPMENT.start
      || value.population.endDate !== CURRENT_DEVELOPMENT.end
      || value.population.finalOotRows !== CURRENT_FINAL_OOT.rows
      || value.population.finalOotStartDate !== CURRENT_FINAL_OOT.start
      || value.population.finalOotEndDate !== CURRENT_FINAL_OOT.end
      || value.authority.splitContractId !== CURRENT_SPLIT_ID
      || value.authority.outlierPolicyId !== CURRENT_OUTLIER_ID
      || value.authority.missingPolicyId !== CURRENT_MISSING_ID
      || value.authority.targetOrder.length !== CURRENT_TARGET_ORDER.length
      || CURRENT_TARGET_ORDER.some((target, index) => value.authority.targetOrder[index] !== target)
    ))
  ) throw new Error("Candidate Evaluation did not preserve the exact project-bound development authority and final-OOT lock.");
  return value;
}

export async function fetchProjectCandidateEvaluation(projectId: string, signal?: AbortSignal) {
  const value = await getJSON<ProjectCandidateEvaluation>(evaluationPrefix(projectId), { signal, credentials: "include" });
  return assertEvaluation(value, projectId);
}

export async function saveProjectCandidateFinalists(
  projectId: string,
  payload: SaveProjectCandidateFinalistsPayload,
  signal?: AbortSignal,
) {
  return postJSON<{ ok: true; selection: Record<string, any> }>(
    `${evaluationPrefix(projectId)}/finalists`,
    payload,
    signal,
  );
}

export async function requestProjectCandidateAnalysis(
  projectId: string,
  payload: {
    candidateFingerprint: string;
    analysisKind: "PERMUTATION_IMPORTANCE" | "SHAP" | "SENSITIVITY";
    sampleSize: number;
    seed: number;
    targetClass: string;
  },
  signal?: AbortSignal,
) {
  return postJSON<{ ok: true; analysis: Record<string, any> }>(
    `${evaluationPrefix(projectId)}/analysis`, payload, signal,
  );
}

export async function planProjectModelRefinement(
  projectId: string,
  payload: {
    candidateFingerprint: string;
    method: string;
    minimumRetainedFeatures: number;
    eliminationStep: number;
    rationale: string;
  },
  signal?: AbortSignal,
) {
  return postJSON<{ ok: true; plan: Record<string, any> }>(
    `/projects/${encodeURIComponent(projectId)}/sports/stage3-model-refinement/plan`,
    payload,
    signal,
  );
}

export async function executeProjectModelRefinement(
  projectId: string,
  planId: string,
  signal?: AbortSignal,
) {
  return postJSON<{ ok: true; job: ModelDevelopmentJob; refinement: Record<string, any> }>(
    `/projects/${encodeURIComponent(projectId)}/sports/stage3-model-refinement/execute`,
    { planId },
    signal,
  );
}

const downstreamPrefix = (projectId: string) =>
  `/projects/${encodeURIComponent(projectId)}/sports/stage3-downstream`;

function assertProjectStage3Downstream(value: ProjectStage3Downstream, projectId: string) {
  if (
    value?.ok !== true
    || value.authority?.projectId !== projectId
    || !value.authority?.goldDatasetId
    || !value.authority?.goldManifestSha
    || value.authority?.legacyGlobalMatrixUsed !== false
    || value.authority?.base22FallbackAvailable === true
    || value.population?.scope !== "DEVELOPMENT_ONLY"
    || value.population?.developmentRows <= 0
    || value.population?.finalOotLocked !== true
    || value.population?.finalOotTargetAccessed !== false
    || value.population?.finalOotScored !== false
    || !Array.isArray(value.finalists)
    || !Array.isArray(value.calibrationDecisions)
    || !Array.isArray(value.gameEvaluationDecisions)
    || !Array.isArray(value.selectionDecisions)
    || !Array.isArray(value.registryEntries)
    || (value.activity?.providerCalls ?? 0) !== 0
    || (value.activity?.modelsPromoted ?? 0) !== 0
    || (value.activity?.newFitsOnPageLoad ?? 0) !== 0
    || (value.activity?.calibrationFits ?? 0) !== 0
    || (value.activity?.simulationRuns ?? 0) !== 0
    || (value.activity?.finalOotRowsAccessed ?? 0) !== 0
    || (value.activity?.modelsExported ?? 0) !== 0
    || (projectId === CURRENT_PROJECT_ID && (
      value.authority.goldDatasetId !== CURRENT_GOLD_ID
      || value.authority.goldManifestSha !== CURRENT_GOLD_MANIFEST
      || value.population.developmentRows !== CURRENT_DEVELOPMENT.rows
      || value.population.startDate !== CURRENT_DEVELOPMENT.start
      || value.population.endDate !== CURRENT_DEVELOPMENT.end
      || value.population.finalOotRows !== CURRENT_FINAL_OOT.rows
      || value.population.finalOotStartDate !== CURRENT_FINAL_OOT.start
      || value.population.finalOotEndDate !== CURRENT_FINAL_OOT.end
    ))
  ) throw new Error("The downstream workflow did not preserve the exact project-bound development authority, zero-promotion state, and final-OOT lock.");
  return value;
}

export async function fetchProjectStage3Downstream(projectId: string, signal?: AbortSignal) {
  const value = await getJSON<ProjectStage3Downstream>(downstreamPrefix(projectId), {
    signal,
    credentials: "include",
  });
  return assertProjectStage3Downstream(value, projectId);
}

export async function saveProjectCalibrationDecision(
  projectId: string,
  payload: {
    candidateFingerprint: string;
    disposition: "RETAIN_RAW" | "DEFER_RECALIBRATION";
    rationale: string;
  },
  signal?: AbortSignal,
) {
  return postJSON<{ ok: true; decision: ProjectDownstreamDecision }>(
    `${downstreamPrefix(projectId)}/calibration`, payload, signal,
  );
}

export async function saveProjectGameEvaluationDecision(
  projectId: string,
  payload: {
    candidateFingerprint: string;
    disposition: "DEFER_UNTIL_EXECUTABLE_ARTIFACT";
    rationale: string;
  },
  signal?: AbortSignal,
) {
  return postJSON<{ ok: true; decision: ProjectDownstreamDecision }>(
    `${downstreamPrefix(projectId)}/game-evaluation`, payload, signal,
  );
}

export async function saveProjectResearchSelection(
  projectId: string,
  payload: {
    candidateFingerprint: string;
    decision: "REGISTER_RESEARCH_CHALLENGER" | "KEEP_INCUMBENT" | "DEFER_DECISION";
    rationale: string;
  },
  signal?: AbortSignal,
) {
  return postJSON<{ ok: true; decision: ProjectDownstreamDecision }>(
    `${downstreamPrefix(projectId)}/selection`, payload, signal,
  );
}

export async function registerProjectResearchHandoff(
  projectId: string,
  selectionId: string,
  signal?: AbortSignal,
) {
  return postJSON<{ ok: true; entry: ProjectDownstreamDecision; idempotentReplay: boolean }>(
    `${downstreamPrefix(projectId)}/registry`, { selectionId }, signal,
  );
}

/** @deprecated Normal UI execution uses the planned, persisted job queue. */
export async function runProjectModelLab(
  projectId: string,
  summary: ProjectModelLabSummary,
  candidates: { modelFamily: string; featureSetId: string | null }[],
  signal?: AbortSignal,
) {
  const path = `${prefix(projectId)}/run`;
  const response = await fetch(`${BASE}${path}`, {
    method: "POST",
    body: JSON.stringify({
      authorityKey: summary.authority.authorityKey,
      splitContractId: summary.split.splitContractId,
      outlierPolicyId: summary.policies.outlier.policyId,
      missingPolicyId: summary.policies.missing.policyId,
      candidates,
      seed: 731026,
      smoke: false,
    }),
    signal,
    credentials: "include",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
  });
  const value = await response.json().catch(() => null) as RunEnvelope | null;
  if (!response.ok) throw exactHttpError(value, response.status, path);
  if (value?.ok !== true || !value.run) throw new Error("The Model Laboratory run response was incomplete.");
  return assertRun(normalizedRun(value.run), summary);
}
