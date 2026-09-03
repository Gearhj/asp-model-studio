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

export type Stage3ResearchModelStatus = "RESEARCH_CHALLENGER";
export type Stage3ResearchPromotionStatus = "NOT_PROMOTED";
export type Stage3VerificationStatus = "PASS" | "FAILED";
export type Stage3ArtifactJobStatus =
  | "QUEUED"
  | "RUNNING"
  | "CANCEL_REQUESTED"
  | "CANCELLED"
  | "INTERRUPTED"
  | "FAILED"
  | "COMPLETE";
export type Stage3ArtifactProgressState =
  | "QUEUED"
  | "PENDING"
  | "CREATING"
  | "VERIFYING"
  | "RUNNING"
  | "CANCELLED"
  | "INTERRUPTED"
  | "COMPLETE"
  | "FAILED"
  | "SKIPPED";

export type Stage3ExecutableArtifactAuthority = {
  projectId: string;
  projectName: string;
  sourceDatasetId: string;
  sourceManifestSha: string;
  goldDatasetId: string;
  goldManifestSha: string;
  contextualManifestSha: string;
  authorityKey: string;
  splitContractId: string;
  splitVersion: number;
  splitChecksum: string;
  outlierPolicyId: string;
  outlierPolicyVersion: number;
  outlierPolicyChecksum: string;
  missingPolicyId: string;
  missingPolicyVersion: number;
  missingPolicyChecksum: string;
  targetOrder: string[];
  developmentRows: number;
  developmentStart: string;
  developmentEnd: string;
  finalOotRows: number;
  finalOotStart: string;
  finalOotEnd: string;
  finalOotLocked: true;
  finalOotTargetAccessed: false;
};

export type Stage3ExecutableArtifactSelection = {
  finalistSelectionId: string;
  calibrationDecisionId: string;
  gameEvaluationDecisionId: string;
  selectionDecisionId: string;
  researchHandoffId: string;
  registryEntryId: string;
  candidateFingerprint: string;
  candidateAttemptId: string;
  candidateAttemptReceiptSha256: string;
  candidateRunId: string;
  candidateRunReceiptSha256: string;
  modelStatus: Stage3ResearchModelStatus;
  promotionStatus: Stage3ResearchPromotionStatus;
};

export type Stage3ArtifactSafety = {
  modelStatus: Stage3ResearchModelStatus;
  promotionStatus: Stage3ResearchPromotionStatus;
  finalOotLocked: true;
  finalOotTargetAccessed: false;
  providerCalls: 0;
  modelsPromoted: 0;
  championsMutated: 0;
};

export type Stage3ExecutableArtifactPlan = {
  schemaVersion: "SPORTS_STAGE3_EXECUTABLE_ARTIFACT_PLAN_V1";
  planId: string;
  checksum: string;
  createdAt: string;
  createdByUserId: string;
  projectId: string;
  status: string;
  executable: boolean;
  executionBlocker: string | null;
  selection: Stage3ExecutableArtifactSelection;
  candidate: {
    modelFamily: string;
    estimatorClass: "XGBClassifier";
    objective: "multi:softprob";
    evaluationMetric: "mlogloss";
    featureSetId: string;
    featureSetChecksum: string;
    featureCount: number;
    orderedFeaturesSha256: string;
    hyperparameters: Record<string, unknown>;
    seed: number;
    targetOrder: string[];
    acceptedOofEvidenceSha256: string;
    acceptedModelLabImplementationSha256: string;
  };
  authority: Stage3ExecutableArtifactAuthority;
  workload: {
    foldCount: number;
    oofRows: number;
    finalFitRows: number;
    modelFits: number;
    estimatedSecondsFromAcceptedRun: number;
  };
  execution: {
    nativeWorkers: number;
    computeClass: string;
    exclusiveCandidate: true;
    maximumConcurrentSameAlgorithm: 1;
    nestedOversubscriptionProhibited: true;
    schedulingPolicy: string;
  };
  expectedArtifacts: string[];
  safety: Stage3ArtifactSafety;
};

export type Stage3ExecutableArtifact = {
  artifactId: string;
  status: "EXECUTABLE_RESEARCH_ARTIFACT_MATERIALIZED";
  manifestSha256: string;
  modelSha256: string;
  preprocessingSha256: string;
  oofArtifactSha256: string;
  oofRows: number;
  metricReproduction: { status: Stage3VerificationStatus; maxAbsoluteDifference: number };
  reloadVerification: { status: Stage3VerificationStatus; freshProcess: boolean };
  verificationFixture: { status: Stage3VerificationStatus; maxAbsoluteDifference: number };
  trainingRows: number;
  trainingCutoff: string;
  modelStatus: Stage3ResearchModelStatus;
  promotionStatus: Stage3ResearchPromotionStatus;
  finalOotLocked: true;
};

export type Stage3ExecutableArtifactFailure = Omit<Stage3ExecutableArtifact, "status"> & {
  status: "EXECUTABLE_RESEARCH_ARTIFACT_VERIFICATION_FAILED";
  verificationError: { code: string; message: string };
};

export type Stage3ExecutableArtifactJob = {
  schemaVersion: "SPORTS_STAGE3_EXECUTABLE_ARTIFACT_JOB_V1";
  jobId: string;
  projectId: string;
  status: Stage3ArtifactJobStatus;
  plan: Stage3ExecutableArtifactPlan;
  progress: {
    state: Stage3ArtifactProgressState;
    currentFold: number | null;
    foldRowsProcessed: number;
    oofRowsPersisted: number;
    finalFitState: Stage3ArtifactProgressState;
    artifactStagingState: Stage3ArtifactProgressState;
    reloadVerificationState: Stage3ArtifactProgressState;
    elapsedSeconds: number;
    latestCheckpoint: string | null;
    message: string;
  };
  artifact: Stage3ExecutableArtifact | null;
  error: { code: string; message: string } | null;
  createdAt: string;
  startedAt: string | null;
  completedAt: string | null;
  idempotentReplay?: boolean;
  safety: Stage3ArtifactSafety;
};

export type ProjectStage3ExecutableArtifact = {
  ok: true;
  schemaVersion: "SPORTS_STAGE3_EXECUTABLE_ARTIFACT_SUMMARY_V1";
  authority: Stage3ExecutableArtifactAuthority;
  selection: Stage3ExecutableArtifactSelection;
  artifact: Stage3ExecutableArtifact | Stage3ExecutableArtifactFailure | null;
  currentJob: Stage3ExecutableArtifactJob | null;
  gates: {
    researchChallengerCurrent: boolean;
    artifactPlanReady: boolean;
    artifactJobActive: boolean;
    artifactReady: boolean;
    scoringReady: boolean;
  };
  limitations: string[];
  safety: Stage3ArtifactSafety;
  activity: {
    modelFitsByPurpose: { oofFold: number; finalDevelopment: number };
    finalOotRowsAccessed: 0;
    providerCalls: 0;
    modelsPromoted: 0;
    championsMutated: 0;
  };
};

export type Stage3EvidenceReference = {
  status: string;
  authorityId: string;
  sourceId: string;
  checksumSha256: string;
};

export type Stage3GameReadiness = {
  schemaVersion: "SPORTS_STAGE3_GAME_READINESS_V1";
  gameId: string | null;
  gameDate: string | null;
  homeTeamId: string | null;
  awayTeamId: string | null;
  scheduledFirstPitch: string | null;
  lineupEvidence: Stage3EvidenceReference | null;
  starterEvidence: Stage3EvidenceReference | null;
  featureCutoff: string | null;
  missingPredictors: string[];
  scoreable: boolean;
  status: "SCOREABLE" | "BLOCKED";
  blockedReasons: Array<{ code: string; message: string }>;
};

export type Stage3JointScoreBin = {
  awayRuns: number;
  homeRuns: number;
  count: number;
  probability: number;
};

export type Stage3ScoreBin = {
  count: number;
  probability: number;
  awayRuns?: number;
  homeRuns?: number;
  homeRunDifference?: number;
  totalRuns?: number;
};

export type Stage3PredictionInterval = { p05: number; p50: number; p95: number };

export type Stage3GovernedGameScore = {
  schemaVersion: string;
  gameId: string;
  gameDate: string;
  evidenceStatus: "GOVERNED_PREGAME_EVIDENCE_VERIFIED";
  scoringMode: "HISTORICAL_OOF" | "PROSPECTIVE";
  foldModelUsed: string | null;
  finalModelUsed: boolean;
  validationStartDate?: string;
  validationEndDate?: string;
  trainedThrough?: string;
  lineupAuthority: Stage3EvidenceReference;
  starterAuthority: Stage3EvidenceReference;
  featureAuthority: Stage3EvidenceReference;
  featureCutoff: string;
  artifactId: string;
  artifactManifestSha256: string;
  modelBinarySha256: string;
  featureVectorSha256: string;
  transitionModelSha256: string;
  draws: number;
  seed: number;
  rngLineage: {
    masterSeed: number;
    gameKey: string;
    gameSeed: number;
    childDerivation: string;
  };
  externalProviderCalls: 0;
  actualTargetOutcomesRead: false;
  actualSubstitutionsUsed: false;
  actualRelieversUsed: false;
  sportsbookPredictorsUsed: false;
  expectedHomeRuns: number;
  expectedAwayRuns: number;
  homeWinProbability: number;
  awayWinProbability: number;
  jointScoreDistribution: Stage3JointScoreBin[];
  awayScoreDistribution: Stage3ScoreBin[];
  homeScoreDistribution: Stage3ScoreBin[];
  runDifferenceDistribution: Stage3ScoreBin[];
  totalRunsDistribution: Stage3ScoreBin[];
  firstFive: {
    completedDraws: number;
    expectedHomeRuns: number;
    expectedAwayRuns: number;
    homeWinProbability: number;
    awayWinProbability: number;
    tieProbability: number;
    jointScoreDistribution: Stage3JointScoreBin[];
    totalRunsDistribution: Stage3ScoreBin[];
    predictionIntervals: {
      awayRuns90: Stage3PredictionInterval;
      homeRuns90: Stage3PredictionInterval;
      totalRuns90: Stage3PredictionInterval;
    };
  };
  mostLikelyScores: Stage3JointScoreBin[];
  predictionIntervals: {
    awayRuns90: Stage3PredictionInterval;
    homeRuns90: Stage3PredictionInterval;
    totalRuns90: Stage3PredictionInterval;
    homeRunDifference90: Stage3PredictionInterval;
  };
  extraInningProbability: number;
  uncertainty: {
    expectedAwayRunsStandardError: number;
    expectedHomeRunsStandardError: number;
    homeWinProbabilityStandardError: number;
  };
  stability: {
    method: string;
    blocks: Array<{
      block: number;
      draws: number;
      expectedAwayRuns: number;
      expectedHomeRuns: number;
      homeWinProbability: number;
    }>;
    maxExpectedAwayRunsSpread: number;
    maxExpectedHomeRunsSpread: number;
    maxHomeWinProbabilitySpread: number;
  };
  reconciliation: {
    status: "PASSED";
    jointDistributionNormalized: true;
    jointAndMarginalsReconciled: true;
    marginAndTotalReconciled: true;
    expectedScoresReconciled: true;
    homeAwayWinsReconciled: true;
    firstFiveReconciled: true;
    legalBaseOutStates: true;
    allDrawsTerminated: true;
  };
  scoringReceiptSha256: string;
};

export type Stage3GameScoringJobStatus = "QUEUED" | "RUNNING" | "CANCEL_REQUESTED" | "COMPLETE" | "FAILED";

export type Stage3GameScoringJob = {
  jobId: string;
  projectId: string;
  status: Stage3GameScoringJobStatus;
  createdBy: string;
  startedAt: string | null;
  completedAt: string | null;
  request: {
    artifactId: string;
    gameIds: string[];
    draws: number;
    seed: number;
  };
  progress: {
    state: string;
    statusMessage: string;
    gamesTotal: number;
    gamesCompleted: number;
    currentGameId: string | null;
    drawsPerGame: number;
    latestCheckpoint: string | null;
    elapsedMs: number;
  };
  results: Stage3GovernedGameScore[];
  error: { code: string; message: string } | null;
};

export type ProjectStage3GameScoring = {
  ok: true;
  schemaVersion: "SPORTS_STAGE3_GOVERNED_GAME_SCORING_V1";
  authority: {
    projectId: string;
    artifactId: string | null;
    artifactManifestSha256: string | null;
    artifactStatus: string | null;
    modelStatus: Stage3ResearchModelStatus;
    promotionStatus: Stage3ResearchPromotionStatus;
    finalOotLocked: true;
  };
  readiness: {
    ready: boolean;
    status: string;
    blockers: Array<{ code: string; message: string }>;
  };
  games: Stage3GameReadiness[];
  currentJob: Stage3GameScoringJob | null;
  results: Stage3GovernedGameScore[];
  activity: {
    providerCalls: 0;
    finalOotTargetAccessed: false;
    actualTargetOutcomesRead: false;
    gamesDiscovered: number;
    jobs: Stage3GameScoringJob[];
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
const CURRENT_SPLIT_CHECKSUM = "488ac1a6a6a1d97c88829a251f7e0d9e48e1b561797e7c750d7d2576aa9b11ac";
const CURRENT_OUTLIER_ID = "stage3-outlier-policy-facf3b3cb90348e68fd349d14733d87a";
const CURRENT_OUTLIER_VERSION = 2;
const CURRENT_OUTLIER_CHECKSUM = "89cf839e9780f796b0317222b555f255f26b3e2270c0590751123345782c2ab8";
const CURRENT_MISSING_ID = "stage3-imputation-policy-75a1080b57b14165b22ed348f11d6896";
const CURRENT_MISSING_VERSION = 2;
const CURRENT_MISSING_CHECKSUM = "e6b4e187d24dc4c7960b3d76ffbf8b88df67d4a845a5810588259e1f097aee06";
const CURRENT_CONTEXTUAL_MANIFEST = "4c228116951a3505d6a5d955f00cd2b92b35b1ccb85c7c69d11d77828485320e";
const CURRENT_SOURCE_DATASET = "asp.mlb.statcast.current-pa.v1";
const CURRENT_SOURCE_MANIFEST = "03ca6dab30e760b2b86b65308090c2d358a67127cc34dfde7a75fc198c3ba84c";
const CURRENT_FINALIST_SELECTION = "stage3-finalist-selection-634c2b48c4224a23878d5dc07b10afe8";
const CURRENT_CALIBRATION_DECISION = "stage3-calibration-decision-83a7738b83d149859517099b361b6b62";
const CURRENT_GAME_EVALUATION_DECISION = "stage3-game-evaluation-decision-59c8d32c50ef41f78a224ccb9773ed40";
const CURRENT_SELECTION_DECISION = "stage3-challenger-decision-8c0c7211d9c64466b95af9607ca3376c";
const CURRENT_RESEARCH_HANDOFF = "stage3-research-handoff-e9c5ac58b8414b15ac90eb50ce5ca50d";
const CURRENT_REGISTRY_ENTRY = "stage3-research-challenger-94c31d6992a84b70aa5827e4cf81da05";
const CURRENT_CHALLENGER_FINGERPRINT = "stage3-candidate-spec-1348285dbc6b9afb0445f0c26953564675c2afb4a4d838aff913314d85e71138";
const CURRENT_CHALLENGER_ATTEMPT = "stage3-candidate-5b7841353fa24b22ae669b104b0afb20";
const CURRENT_CHALLENGER_ATTEMPT_RECEIPT = "89487692000cd909361207ac0ffcd3f12b3a8e3dda4d9a80163a6420b1f24d85";
const CURRENT_CHALLENGER_RUN = "stage3-model-development-run-9dcba47415584a38ae6e2c1437e69472";
const CURRENT_CHALLENGER_RUN_RECEIPT = "932211b901ed8cee25b95f4fb7a05c2a207e222719c81e83fc03490213441553";
const CURRENT_CHALLENGER_FEATURE_SET = "stage3-full-eligible-modeling-set-7fcc655c652527df723d581771db56b1";
const CURRENT_CHALLENGER_FEATURE_CHECKSUM = "7fcc655c652527df723d581771db56b18c0c46bb9cb71000048d80b0da4230d8";
const CURRENT_CHALLENGER_FEATURE_COUNT = 234;
const CURRENT_CHALLENGER_SEED = 20260901;
const CURRENT_OOF_ROWS = 501_590;
const CURRENT_OOF_EVIDENCE_SHA = "9a93f4ef963ae2fdbe5eb25f5115a2f47dcff5428ef85e6627a9a00d0655410f";
const CURRENT_MODEL_LAB_IMPLEMENTATION_SHA = "af10a7aba685b13da9526c037bfb086c081ff1938ffd4c6c9ef90e54ae474ed2";

function exactHttpError(value: any, status: number, path: string): Error {
  const detail = value?.detail;
  const code = typeof detail === "object" ? String(detail?.code || "") : "";
  const message = typeof detail === "object"
    ? String(detail?.message || "")
    : typeof detail === "string" ? detail : "";
  return new Error([code, message].filter(Boolean).join(": ") || `${path} failed: ${status}`);
}

const SHA256 = /^[a-f0-9]{64}$/;
const ARTIFACT_TERMINAL = new Set<Stage3ArtifactJobStatus>(["CANCELLED", "INTERRUPTED", "FAILED", "COMPLETE"]);

function record(value: unknown): value is Record<string, any> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function sha256(value: unknown): value is string {
  return typeof value === "string" && SHA256.test(value);
}

function nonnegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function nonnegativeJsonInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && Number.isInteger(value) && value >= 0;
}

function exactTargetOrder(value: unknown): value is string[] {
  return Array.isArray(value)
    && value.length === CURRENT_TARGET_ORDER.length
    && CURRENT_TARGET_ORDER.every((target, index) => value[index] === target);
}

function exactArtifactAuthority(value: unknown, projectId: string): value is Stage3ExecutableArtifactAuthority {
  if (!record(value)) return false;
  const basic = value.projectId === projectId
    && nonEmptyString(value.projectName)
    && nonEmptyString(value.sourceDatasetId)
    && sha256(value.sourceManifestSha)
    && nonEmptyString(value.goldDatasetId)
    && sha256(value.goldManifestSha)
    && sha256(value.contextualManifestSha)
    && nonEmptyString(value.authorityKey)
    && nonEmptyString(value.splitContractId)
    && nonnegativeInteger(value.splitVersion)
    && sha256(value.splitChecksum)
    && nonEmptyString(value.outlierPolicyId)
    && nonnegativeInteger(value.outlierPolicyVersion)
    && sha256(value.outlierPolicyChecksum)
    && nonEmptyString(value.missingPolicyId)
    && nonnegativeInteger(value.missingPolicyVersion)
    && sha256(value.missingPolicyChecksum)
    && exactTargetOrder(value.targetOrder)
    && nonnegativeInteger(value.developmentRows)
    && nonEmptyString(value.developmentStart)
    && nonEmptyString(value.developmentEnd)
    && nonnegativeInteger(value.finalOotRows)
    && nonEmptyString(value.finalOotStart)
    && nonEmptyString(value.finalOotEnd)
    && value.finalOotLocked === true
    && value.finalOotTargetAccessed === false;
  if (!basic || projectId !== CURRENT_PROJECT_ID) return basic;
  return value.goldDatasetId === CURRENT_GOLD_ID
    && value.sourceDatasetId === CURRENT_SOURCE_DATASET
    && value.sourceManifestSha === CURRENT_SOURCE_MANIFEST
    && value.goldManifestSha === CURRENT_GOLD_MANIFEST
    && value.contextualManifestSha === CURRENT_CONTEXTUAL_MANIFEST
    && value.splitContractId === CURRENT_SPLIT_ID
    && value.splitVersion === 2
    && value.splitChecksum === CURRENT_SPLIT_CHECKSUM
    && value.outlierPolicyId === CURRENT_OUTLIER_ID
    && value.outlierPolicyVersion === CURRENT_OUTLIER_VERSION
    && value.outlierPolicyChecksum === CURRENT_OUTLIER_CHECKSUM
    && value.missingPolicyId === CURRENT_MISSING_ID
    && value.missingPolicyVersion === CURRENT_MISSING_VERSION
    && value.missingPolicyChecksum === CURRENT_MISSING_CHECKSUM
    && value.developmentRows === CURRENT_DEVELOPMENT.rows
    && value.developmentStart === CURRENT_DEVELOPMENT.start
    && value.developmentEnd === CURRENT_DEVELOPMENT.end
    && value.finalOotRows === CURRENT_FINAL_OOT.rows
    && value.finalOotStart === CURRENT_FINAL_OOT.start
    && value.finalOotEnd === CURRENT_FINAL_OOT.end;
}

function exactArtifactSelection(value: unknown, projectId: string): value is Stage3ExecutableArtifactSelection {
  if (!record(value)) return false;
  const basic = nonEmptyString(value.finalistSelectionId)
    && nonEmptyString(value.calibrationDecisionId)
    && nonEmptyString(value.gameEvaluationDecisionId)
    && nonEmptyString(value.selectionDecisionId)
    && nonEmptyString(value.researchHandoffId)
    && nonEmptyString(value.registryEntryId)
    && nonEmptyString(value.candidateFingerprint)
    && nonEmptyString(value.candidateAttemptId)
    && sha256(value.candidateAttemptReceiptSha256)
    && nonEmptyString(value.candidateRunId)
    && sha256(value.candidateRunReceiptSha256)
    && value.modelStatus === "RESEARCH_CHALLENGER"
    && value.promotionStatus === "NOT_PROMOTED";
  if (!basic || projectId !== CURRENT_PROJECT_ID) return basic;
  return value.finalistSelectionId === CURRENT_FINALIST_SELECTION
    && value.calibrationDecisionId === CURRENT_CALIBRATION_DECISION
    && value.gameEvaluationDecisionId === CURRENT_GAME_EVALUATION_DECISION
    && value.selectionDecisionId === CURRENT_SELECTION_DECISION
    && value.researchHandoffId === CURRENT_RESEARCH_HANDOFF
    && value.registryEntryId === CURRENT_REGISTRY_ENTRY
    && value.candidateFingerprint === CURRENT_CHALLENGER_FINGERPRINT
    && value.candidateAttemptId === CURRENT_CHALLENGER_ATTEMPT
    && value.candidateAttemptReceiptSha256 === CURRENT_CHALLENGER_ATTEMPT_RECEIPT
    && value.candidateRunId === CURRENT_CHALLENGER_RUN
    && value.candidateRunReceiptSha256 === CURRENT_CHALLENGER_RUN_RECEIPT;
}

function exactArtifactSafety(value: unknown): value is Stage3ArtifactSafety {
  return record(value)
    && value.modelStatus === "RESEARCH_CHALLENGER"
    && value.promotionStatus === "NOT_PROMOTED"
    && value.finalOotLocked === true
    && value.finalOotTargetAccessed === false
    && value.providerCalls === 0
    && value.modelsPromoted === 0
    && value.championsMutated === 0;
}

function exactFrozenXgboostCandidate(value: unknown, projectId: string): value is Stage3ExecutableArtifactPlan["candidate"] {
  if (!record(value) || !record(value.hyperparameters)) return false;
  const hyperparameters = value.hyperparameters;
  const basic = nonEmptyString(value.modelFamily)
    && value.estimatorClass === "XGBClassifier"
    && value.objective === "multi:softprob"
    && value.evaluationMetric === "mlogloss"
    && nonEmptyString(value.featureSetId)
    && sha256(value.featureSetChecksum)
    && nonnegativeInteger(value.featureCount)
    && sha256(value.orderedFeaturesSha256)
    && nonnegativeInteger(value.seed)
    && exactTargetOrder(value.targetOrder)
    && sha256(value.acceptedOofEvidenceSha256)
    && sha256(value.acceptedModelLabImplementationSha256);
  if (!basic || projectId !== CURRENT_PROJECT_ID) return basic;
  return value.modelFamily === "xgboost"
    && value.featureSetId === CURRENT_CHALLENGER_FEATURE_SET
    && value.featureSetChecksum === CURRENT_CHALLENGER_FEATURE_CHECKSUM
    && value.featureCount === CURRENT_CHALLENGER_FEATURE_COUNT
    && value.seed === CURRENT_CHALLENGER_SEED
    && value.acceptedOofEvidenceSha256 === CURRENT_OOF_EVIDENCE_SHA
    && value.acceptedModelLabImplementationSha256 === CURRENT_MODEL_LAB_IMPLEMENTATION_SHA
    && hyperparameters.n_estimators === 300
    && hyperparameters.learning_rate === 0.07
    && hyperparameters.max_depth === 5
    && hyperparameters.min_child_weight === 1
    && hyperparameters.subsample === 0.8
    && hyperparameters.colsample_bytree === 0.7
    && Number(hyperparameters.gamma) === 0
    && Number(hyperparameters.reg_alpha) === 0
    && Number(hyperparameters.reg_lambda) === 1;
}

function exactArtifactPlan(value: unknown, projectId: string): value is Stage3ExecutableArtifactPlan {
  if (!record(value) || value.projectId !== projectId) return false;
  if (
    value.schemaVersion !== "SPORTS_STAGE3_EXECUTABLE_ARTIFACT_PLAN_V1"
    || !nonEmptyString(value.planId)
    || !sha256(value.checksum)
    || !nonEmptyString(value.createdAt)
    || !nonEmptyString(value.createdByUserId)
    || !nonEmptyString(value.status)
    || typeof value.executable !== "boolean"
    || !(value.executionBlocker === null || nonEmptyString(value.executionBlocker))
    || !exactArtifactSelection(value.selection, projectId)
    || !exactFrozenXgboostCandidate(value.candidate, projectId)
    || !exactArtifactAuthority(value.authority, projectId)
    || !record(value.workload)
    || !nonnegativeInteger(value.workload.foldCount)
    || !nonnegativeInteger(value.workload.oofRows)
    || !nonnegativeInteger(value.workload.finalFitRows)
    || !nonnegativeInteger(value.workload.modelFits)
    || !finiteNonnegative(value.workload.estimatedSecondsFromAcceptedRun)
    || !record(value.execution)
    || !nonnegativeInteger(value.execution.nativeWorkers)
    || !nonEmptyString(value.execution.computeClass)
    || value.execution.exclusiveCandidate !== true
    || value.execution.maximumConcurrentSameAlgorithm !== 1
    || value.execution.nestedOversubscriptionProhibited !== true
    || !nonEmptyString(value.execution.schedulingPolicy)
    || !Array.isArray(value.expectedArtifacts)
    || value.expectedArtifacts.length === 0
    || value.expectedArtifacts.some((item: unknown) => !nonEmptyString(item))
    || !exactArtifactSafety(value.safety)
  ) return false;
  if (value.executable && value.executionBlocker !== null) return false;
  if (!value.executable && !nonEmptyString(value.executionBlocker)) return false;
  if (projectId === CURRENT_PROJECT_ID && (
    value.workload.foldCount !== 5
    || value.workload.oofRows !== CURRENT_OOF_ROWS
    || value.workload.finalFitRows !== CURRENT_DEVELOPMENT.rows
    || value.workload.modelFits !== 6
    || value.execution.computeClass !== "VERY_HIGH"
  )) return false;
  return true;
}

function exactExecutableArtifact(value: unknown, projectId: string): value is Stage3ExecutableArtifact {
  if (!record(value)) return false;
  const metrics = value.metricReproduction;
  const reload = value.reloadVerification;
  const fixture = value.verificationFixture;
  const valid = nonEmptyString(value.artifactId)
    && value.status === "EXECUTABLE_RESEARCH_ARTIFACT_MATERIALIZED"
    && sha256(value.manifestSha256)
    && sha256(value.modelSha256)
    && sha256(value.preprocessingSha256)
    && sha256(value.oofArtifactSha256)
    && nonnegativeInteger(value.oofRows)
    && record(metrics)
    && metrics.status === "PASS"
    && typeof metrics.maxAbsoluteDifference === "number"
    && Number.isFinite(metrics.maxAbsoluteDifference)
    && metrics.maxAbsoluteDifference >= 0
    && record(reload)
    && reload.status === "PASS"
    && reload.freshProcess === true
    && record(fixture)
    && fixture.status === "PASS"
    && typeof fixture.maxAbsoluteDifference === "number"
    && Number.isFinite(fixture.maxAbsoluteDifference)
    && fixture.maxAbsoluteDifference >= 0
    && nonnegativeInteger(value.trainingRows)
    && nonEmptyString(value.trainingCutoff)
    && value.modelStatus === "RESEARCH_CHALLENGER"
    && value.promotionStatus === "NOT_PROMOTED"
    && value.finalOotLocked === true;
  if (!valid || projectId !== CURRENT_PROJECT_ID) return valid;
  return value.oofRows === CURRENT_OOF_ROWS
    && value.trainingRows === CURRENT_DEVELOPMENT.rows
    && value.trainingCutoff === CURRENT_DEVELOPMENT.end;
}

function exactExecutableArtifactFailure(value: unknown, projectId: string): value is Stage3ExecutableArtifactFailure {
  if (!record(value)
    || value.status !== "EXECUTABLE_RESEARCH_ARTIFACT_VERIFICATION_FAILED"
    || !exactBlockedReason(value.verificationError)) return false;
  return exactExecutableArtifact({ ...value, status: "EXECUTABLE_RESEARCH_ARTIFACT_MATERIALIZED" }, projectId);
}

function exactArtifactJob(value: unknown, projectId: string): value is Stage3ExecutableArtifactJob {
  if (!record(value)
    || value.schemaVersion !== "SPORTS_STAGE3_EXECUTABLE_ARTIFACT_JOB_V1"
    || !nonEmptyString(value.jobId)
    || value.projectId !== projectId
    || !exactArtifactSafety(value.safety)) return false;
  if (!(["QUEUED", "RUNNING", "CANCEL_REQUESTED", "CANCELLED", "INTERRUPTED", "FAILED", "COMPLETE"] as unknown[]).includes(value.status)) return false;
  if (!exactArtifactPlan(value.plan, projectId) || !record(value.progress)) return false;
  const progress = value.progress;
  if (
    !(["QUEUED", "PENDING", "CREATING", "VERIFYING", "RUNNING", "CANCELLED", "INTERRUPTED", "COMPLETE", "FAILED", "SKIPPED"] as unknown[]).includes(progress.state)
    || !(progress.currentFold === null || nonnegativeInteger(progress.currentFold))
    || !nonnegativeInteger(progress.foldRowsProcessed)
    || !nonnegativeInteger(progress.oofRowsPersisted)
    || !(["PENDING", "RUNNING", "COMPLETE", "FAILED", "SKIPPED"] as unknown[]).includes(progress.finalFitState)
    || !(["PENDING", "CREATING", "VERIFYING", "RUNNING", "COMPLETE", "FAILED", "SKIPPED"] as unknown[]).includes(progress.artifactStagingState)
    || !(["PENDING", "VERIFYING", "RUNNING", "COMPLETE", "FAILED", "SKIPPED"] as unknown[]).includes(progress.reloadVerificationState)
    || typeof progress.elapsedSeconds !== "number"
    || !Number.isFinite(progress.elapsedSeconds)
    || progress.elapsedSeconds < 0
    || !(progress.latestCheckpoint === null || nonEmptyString(progress.latestCheckpoint))
    || !nonEmptyString(progress.message)
    || !nonEmptyString(value.createdAt)
    || !(value.startedAt === null || nonEmptyString(value.startedAt))
    || !(value.completedAt === null || nonEmptyString(value.completedAt))
    || !(value.error === null || (record(value.error) && nonEmptyString(value.error.code) && nonEmptyString(value.error.message)))
  ) return false;
  if (value.status === "COMPLETE") {
    return progress.state === "COMPLETE" && exactExecutableArtifact(value.artifact, projectId) && value.error === null;
  }
  return value.artifact === null;
}

function finiteNonnegative(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function validProbability(value: unknown): value is number {
  return finiteNonnegative(value) && value <= 1;
}

function exactEvidenceReference(value: unknown): value is Stage3EvidenceReference {
  return record(value)
    && nonEmptyString(value.status)
    && nonEmptyString(value.authorityId)
    && nonEmptyString(value.sourceId)
    && sha256(value.checksumSha256);
}

function exactBlockedReason(value: unknown): value is { code: string; message: string } {
  return record(value) && nonEmptyString(value.code) && nonEmptyString(value.message);
}

function exactGameReadiness(value: unknown): value is Stage3GameReadiness {
  if (!record(value) || value.schemaVersion !== "SPORTS_STAGE3_GAME_READINESS_V1") return false;
  if (typeof value.gameDate === "string" && value.gameDate >= CURRENT_FINAL_OOT.start && value.gameDate <= CURRENT_FINAL_OOT.end) return false;
  if (
    !(value.gameId === null || nonEmptyString(value.gameId))
    || !(value.gameDate === null || nonEmptyString(value.gameDate))
    || !(value.homeTeamId === null || nonEmptyString(value.homeTeamId))
    || !(value.awayTeamId === null || nonEmptyString(value.awayTeamId))
    || !(value.scheduledFirstPitch === null || nonEmptyString(value.scheduledFirstPitch))
    || !(value.lineupEvidence === null || exactEvidenceReference(value.lineupEvidence))
    || !(value.starterEvidence === null || exactEvidenceReference(value.starterEvidence))
    || !(value.featureCutoff === null || nonEmptyString(value.featureCutoff))
    || !Array.isArray(value.missingPredictors)
    || value.missingPredictors.some((item: unknown) => !nonEmptyString(item))
    || typeof value.scoreable !== "boolean"
    || value.status !== (value.scoreable ? "SCOREABLE" : "BLOCKED")
    || !Array.isArray(value.blockedReasons)
    || value.blockedReasons.some((item: unknown) => !exactBlockedReason(item))
  ) return false;
  if (value.scoreable) {
    return nonEmptyString(value.gameId)
      && nonEmptyString(value.gameDate)
      && !(value.gameDate >= CURRENT_FINAL_OOT.start && value.gameDate <= CURRENT_FINAL_OOT.end)
      && nonEmptyString(value.homeTeamId)
      && nonEmptyString(value.awayTeamId)
      && value.homeTeamId !== value.awayTeamId
      && nonEmptyString(value.scheduledFirstPitch)
      && exactEvidenceReference(value.lineupEvidence)
      && value.lineupEvidence.status === "CONFIRMED"
      && exactEvidenceReference(value.starterEvidence)
      && ["CONFIRMED", "ANNOUNCED_CONFIRMED"].includes(value.starterEvidence.status)
      && nonEmptyString(value.featureCutoff)
      && value.featureCutoff < value.scheduledFirstPitch
      && value.blockedReasons.length === 0;
  }
  return value.blockedReasons.length > 0;
}

function closeToOne(value: number): boolean {
  return Math.abs(value - 1) <= 1e-9;
}

function exactJointDistribution(value: unknown, draws: number, allowTies = false): value is Stage3JointScoreBin[] {
  if (!Array.isArray(value) || value.length === 0) return false;
  let counts = 0;
  let probabilityMass = 0;
  const seen = new Set<string>();
  for (const row of value) {
    if (!record(row)
      || !nonnegativeInteger(row.awayRuns)
      || !nonnegativeInteger(row.homeRuns)
      || (!allowTies && row.awayRuns === row.homeRuns)
      || !nonnegativeInteger(row.count)
      || row.count === 0
      || !validProbability(row.probability)
      || Math.abs(row.probability - row.count / draws) > 1e-12) return false;
    const key = `${row.awayRuns}:${row.homeRuns}`;
    if (seen.has(key)) return false;
    seen.add(key);
    counts += row.count;
    probabilityMass += row.probability;
  }
  return counts === draws && closeToOne(probabilityMass);
}

function exactScoreDistribution(
  value: unknown,
  key: "awayRuns" | "homeRuns" | "homeRunDifference" | "totalRuns",
  draws: number,
): value is Stage3ScoreBin[] {
  if (!Array.isArray(value) || value.length === 0) return false;
  let counts = 0;
  let probabilityMass = 0;
  const seen = new Set<number>();
  for (const row of value) {
    const bin = record(row) ? row[key] : null;
    const binValid = key === "homeRunDifference"
      ? typeof bin === "number" && Number.isSafeInteger(bin)
      : nonnegativeInteger(bin);
    if (!record(row)
      || !binValid
      || seen.has(bin)
      || !nonnegativeInteger(row.count)
      || row.count === 0
      || !validProbability(row.probability)
      || Math.abs(row.probability - row.count / draws) > 1e-12) return false;
    seen.add(bin);
    counts += row.count;
    probabilityMass += row.probability;
  }
  return counts === draws && closeToOne(probabilityMass);
}

function exactPredictionInterval(value: unknown, allowNegative = false): value is Stage3PredictionInterval {
  const point = (candidate: unknown): candidate is number => typeof candidate === "number"
    && Number.isFinite(candidate)
    && (allowNegative || candidate >= 0);
  return record(value)
    && point(value.p05)
    && point(value.p50)
    && point(value.p95)
    && value.p05 <= value.p50
    && value.p50 <= value.p95;
}

function exactGovernedGameScore(value: unknown): value is Stage3GovernedGameScore {
  if (!record(value) || !nonEmptyString(value.schemaVersion) || !nonEmptyString(value.gameId) || !nonEmptyString(value.gameDate)) return false;
  if (value.gameDate >= CURRENT_FINAL_OOT.start && value.gameDate <= CURRENT_FINAL_OOT.end) return false;
  if (
    value.evidenceStatus !== "GOVERNED_PREGAME_EVIDENCE_VERIFIED"
    || !["HISTORICAL_OOF", "PROSPECTIVE"].includes(value.scoringMode)
    || typeof value.finalModelUsed !== "boolean"
    || !exactEvidenceReference(value.lineupAuthority)
    || value.lineupAuthority.status !== "CONFIRMED"
    || !exactEvidenceReference(value.starterAuthority)
    || !["CONFIRMED", "ANNOUNCED_CONFIRMED"].includes(value.starterAuthority.status)
    || !exactEvidenceReference(value.featureAuthority)
    || !["COMPLETE", "VERIFIED"].includes(value.featureAuthority.status)
    || !nonEmptyString(value.featureCutoff)
    || !nonEmptyString(value.artifactId)
    || !sha256(value.artifactManifestSha256)
    || !sha256(value.modelBinarySha256)
    || !sha256(value.featureVectorSha256)
    || !sha256(value.transitionModelSha256)
    || !nonnegativeInteger(value.draws)
    || value.draws < 32
    || value.draws > 1_000_000
    || !nonnegativeInteger(value.seed)
    || !record(value.rngLineage)
    || value.rngLineage.masterSeed !== value.seed
    || value.rngLineage.gameKey !== value.gameId
    || !nonnegativeJsonInteger(value.rngLineage.gameSeed)
    || !nonEmptyString(value.rngLineage.childDerivation)
    || value.externalProviderCalls !== 0
    || value.actualTargetOutcomesRead !== false
    || value.actualSubstitutionsUsed !== false
    || value.actualRelieversUsed !== false
    || value.sportsbookPredictorsUsed !== false
    || !finiteNonnegative(value.expectedHomeRuns)
    || !finiteNonnegative(value.expectedAwayRuns)
    || !validProbability(value.homeWinProbability)
    || !validProbability(value.awayWinProbability)
    || !closeToOne(value.homeWinProbability + value.awayWinProbability)
    || !exactJointDistribution(value.jointScoreDistribution, value.draws)
    || !exactScoreDistribution(value.awayScoreDistribution, "awayRuns", value.draws)
    || !exactScoreDistribution(value.homeScoreDistribution, "homeRuns", value.draws)
    || !exactScoreDistribution(value.runDifferenceDistribution, "homeRunDifference", value.draws)
    || !exactScoreDistribution(value.totalRunsDistribution, "totalRuns", value.draws)
  ) return false;
  if (value.scoringMode === "HISTORICAL_OOF") {
    if (!nonEmptyString(value.foldModelUsed)
      || value.finalModelUsed !== false
      || !nonEmptyString(value.validationStartDate)
      || !nonEmptyString(value.validationEndDate)
      || value.gameDate < value.validationStartDate
      || value.gameDate > value.validationEndDate
      || value.trainedThrough !== undefined) return false;
  } else if (value.foldModelUsed !== null
    || value.finalModelUsed !== true
    || !nonEmptyString(value.trainedThrough)
    || value.gameDate <= value.trainedThrough
    || value.validationStartDate !== undefined
    || value.validationEndDate !== undefined) return false;

  const expectedAway = value.jointScoreDistribution.reduce((total: number, row: Stage3JointScoreBin) => total + row.awayRuns * row.probability, 0);
  const expectedHome = value.jointScoreDistribution.reduce((total: number, row: Stage3JointScoreBin) => total + row.homeRuns * row.probability, 0);
  if (Math.abs(expectedAway - value.expectedAwayRuns) > 1e-9 || Math.abs(expectedHome - value.expectedHomeRuns) > 1e-9) return false;

  const first = value.firstFive;
  if (!record(first)
    || first.completedDraws !== value.draws
    || !finiteNonnegative(first.expectedHomeRuns)
    || !finiteNonnegative(first.expectedAwayRuns)
    || !validProbability(first.homeWinProbability)
    || !validProbability(first.awayWinProbability)
    || !validProbability(first.tieProbability)
    || !closeToOne(first.homeWinProbability + first.awayWinProbability + first.tieProbability)
    || !exactJointDistribution(first.jointScoreDistribution, value.draws, true)
    || !exactScoreDistribution(first.totalRunsDistribution, "totalRuns", value.draws)
    || !record(first.predictionIntervals)
    || !exactPredictionInterval(first.predictionIntervals.awayRuns90)
    || !exactPredictionInterval(first.predictionIntervals.homeRuns90)
    || !exactPredictionInterval(first.predictionIntervals.totalRuns90)) return false;

  if (!Array.isArray(value.mostLikelyScores)
    || value.mostLikelyScores.length === 0
    || value.mostLikelyScores.some((row: unknown) => !record(row)
      || !nonnegativeInteger(row.awayRuns)
      || !nonnegativeInteger(row.homeRuns)
      || !nonnegativeInteger(row.count)
      || !validProbability(row.probability))) return false;
  if (!record(value.predictionIntervals)
    || !exactPredictionInterval(value.predictionIntervals.awayRuns90)
    || !exactPredictionInterval(value.predictionIntervals.homeRuns90)
    || !exactPredictionInterval(value.predictionIntervals.totalRuns90)
    || !exactPredictionInterval(value.predictionIntervals.homeRunDifference90, true)) return false;
  if (!validProbability(value.extraInningProbability)
    || !record(value.uncertainty)
    || !finiteNonnegative(value.uncertainty.expectedAwayRunsStandardError)
    || !finiteNonnegative(value.uncertainty.expectedHomeRunsStandardError)
    || !finiteNonnegative(value.uncertainty.homeWinProbabilityStandardError)) return false;
  const stability = value.stability;
  if (!record(stability)
    || !nonEmptyString(stability.method)
    || !Array.isArray(stability.blocks)
    || stability.blocks.length === 0
    || stability.blocks.some((block: unknown) => !record(block)
      || !nonnegativeInteger(block.block)
      || !nonnegativeInteger(block.draws)
      || !finiteNonnegative(block.expectedAwayRuns)
      || !finiteNonnegative(block.expectedHomeRuns)
      || !validProbability(block.homeWinProbability))
    || stability.blocks.reduce((total: number, block: { draws: number }) => total + block.draws, 0) !== value.draws
    || !finiteNonnegative(stability.maxExpectedAwayRunsSpread)
    || !finiteNonnegative(stability.maxExpectedHomeRunsSpread)
    || !finiteNonnegative(stability.maxHomeWinProbabilitySpread)) return false;
  const reconciliation = value.reconciliation;
  return record(reconciliation)
    && reconciliation.status === "PASSED"
    && reconciliation.jointDistributionNormalized === true
    && reconciliation.jointAndMarginalsReconciled === true
    && reconciliation.marginAndTotalReconciled === true
    && reconciliation.expectedScoresReconciled === true
    && reconciliation.homeAwayWinsReconciled === true
    && reconciliation.firstFiveReconciled === true
    && reconciliation.legalBaseOutStates === true
    && reconciliation.allDrawsTerminated === true
    && sha256(value.scoringReceiptSha256);
}

function exactGameScoringRequest(value: unknown): value is Stage3GameScoringJob["request"] {
  return record(value)
    && nonEmptyString(value.artifactId)
    && Array.isArray(value.gameIds)
    && value.gameIds.length > 0
    && value.gameIds.every((item: unknown) => nonEmptyString(item))
    && new Set(value.gameIds).size === value.gameIds.length
    && nonnegativeInteger(value.draws)
    && value.draws >= 32
    && value.draws <= 1_000_000
    && nonnegativeInteger(value.seed);
}

function exactGameScoringJob(value: unknown, projectId: string): value is Stage3GameScoringJob {
  if (!record(value)
    || !nonEmptyString(value.jobId)
    || value.projectId !== projectId
    || !["QUEUED", "RUNNING", "CANCEL_REQUESTED", "COMPLETE", "FAILED"].includes(value.status)
    || !nonEmptyString(value.createdBy)
    || !(value.startedAt === null || nonEmptyString(value.startedAt))
    || !(value.completedAt === null || nonEmptyString(value.completedAt))
    || !exactGameScoringRequest(value.request)
    || !record(value.progress)) return false;
  const progress = value.progress;
  if (!nonEmptyString(progress.state)
    || !nonEmptyString(progress.statusMessage)
    || !nonnegativeInteger(progress.gamesTotal)
    || !nonnegativeInteger(progress.gamesCompleted)
    || progress.gamesCompleted > progress.gamesTotal
    || progress.gamesTotal !== value.request.gameIds.length
    || !(progress.currentGameId === null || (nonEmptyString(progress.currentGameId) && value.request.gameIds.includes(progress.currentGameId)))
    || progress.drawsPerGame !== value.request.draws
    || !(progress.latestCheckpoint === null || nonEmptyString(progress.latestCheckpoint))
    || !finiteNonnegative(progress.elapsedMs)
    || !Array.isArray(value.results)
    || value.results.some((result: unknown) => !exactGovernedGameScore(result))
    || value.results.some((result: Stage3GovernedGameScore) => result.artifactId !== value.request.artifactId || !value.request.gameIds.includes(result.gameId))
    || !(value.error === null || exactBlockedReason(value.error))) return false;
  if (value.status === "COMPLETE") return value.error === null && progress.gamesCompleted === progress.gamesTotal && value.results.length === progress.gamesTotal;
  if (value.status === "FAILED") return value.error !== null;
  return value.error === null;
}

function assertProjectStage3GameScoring(value: unknown, projectId: string): ProjectStage3GameScoring {
  if (!record(value)
    || value.ok !== true
    || value.schemaVersion !== "SPORTS_STAGE3_GOVERNED_GAME_SCORING_V1"
    || !record(value.authority)
    || value.authority.projectId !== projectId
    || value.authority.modelStatus !== "RESEARCH_CHALLENGER"
    || value.authority.promotionStatus !== "NOT_PROMOTED"
    || value.authority.finalOotLocked !== true) {
    throw new Error("The governed-game scoring summary did not preserve research-challenger, zero-promotion, and final-OOT authority.");
  }
  const authority = value.authority;
  const noArtifact = authority.artifactId === null
    && authority.artifactManifestSha256 === null
    && authority.artifactStatus === null;
  const verifiedArtifact = nonEmptyString(authority.artifactId)
    && sha256(authority.artifactManifestSha256)
    && authority.artifactStatus === "EXECUTABLE_RESEARCH_ARTIFACT_MATERIALIZED";
  if (!noArtifact && !verifiedArtifact) throw new Error("Governed-game scoring exposed an incomplete or unverified artifact binding.");
  if (!record(value.readiness)
    || typeof value.readiness.ready !== "boolean"
    || !nonEmptyString(value.readiness.status)
    || !Array.isArray(value.readiness.blockers)
    || value.readiness.blockers.some((item: unknown) => !exactBlockedReason(item))
    || (value.readiness.ready ? value.readiness.blockers.length !== 0 : value.readiness.blockers.length === 0)
    || !Array.isArray(value.games)
    || value.games.some((game: unknown) => !exactGameReadiness(game))
    || !(value.currentJob === null || exactGameScoringJob(value.currentJob, projectId))
    || !Array.isArray(value.results)
    || value.results.some((result: unknown) => !exactGovernedGameScore(result))
    || !record(value.activity)
    || value.activity.providerCalls !== 0
    || value.activity.finalOotTargetAccessed !== false
    || value.activity.actualTargetOutcomesRead !== false
    || !nonnegativeInteger(value.activity.gamesDiscovered)
    || value.activity.gamesDiscovered !== value.games.length
    || !Array.isArray(value.activity.jobs)
    || value.activity.jobs.some((job: unknown) => !exactGameScoringJob(job, projectId))) {
    throw new Error("The governed-game scoring response was incomplete or contained unverified readiness, job, result, provider, or OOT state.");
  }
  if (value.readiness.status === "BLOCKED_MISSING_GOVERNED_PREGAME_AUTHORITY") {
    const exactBlocker = value.readiness.blockers.some((item: { code: string }) => item.code === "GOVERNED_PREGAME_LINEUP_STARTER_AUTHORITY_UNAVAILABLE");
    if (value.readiness.ready || value.games.length !== 0 || !exactBlocker) {
      throw new Error("Current game readiness must remain blocked and empty while governed pregame lineup/starter authority is absent.");
    }
  }
  if (value.readiness.ready && !value.games.some((game: Stage3GameReadiness) => game.scoreable)) {
    throw new Error("Governed-game scoring cannot be ready without at least one independently scoreable game.");
  }
  if (value.results.some((result: Stage3GovernedGameScore) => result.artifactId !== authority.artifactId || result.artifactManifestSha256 !== authority.artifactManifestSha256)) {
    throw new Error("A governed-game result was not bound to the summary's verified artifact.");
  }
  return value as ProjectStage3GameScoring;
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

const executableArtifactPrefix = (projectId: string) =>
  `/projects/${encodeURIComponent(projectId)}/sports/stage3-executable-artifact`;

function assertProjectStage3ExecutableArtifact(
  value: unknown,
  projectId: string,
): ProjectStage3ExecutableArtifact {
  if (!record(value)
    || value.ok !== true
    || value.schemaVersion !== "SPORTS_STAGE3_EXECUTABLE_ARTIFACT_SUMMARY_V1") {
    throw new Error("The executable-artifact summary response was incomplete.");
  }
  const selection = value.selection;
  const artifact = value.artifact;
  const currentJob = value.currentJob;
  const gates = value.gates;
  const activity = value.activity;
  if (
    !exactArtifactAuthority(value.authority, projectId)
    || !exactArtifactSelection(selection, projectId)
    || !(artifact === null || exactExecutableArtifact(artifact, projectId) || exactExecutableArtifactFailure(artifact, projectId))
    || !(currentJob === null || exactArtifactJob(currentJob, projectId))
    || !record(gates)
    || typeof gates.researchChallengerCurrent !== "boolean"
    || typeof gates.artifactPlanReady !== "boolean"
    || typeof gates.artifactJobActive !== "boolean"
    || typeof gates.artifactReady !== "boolean"
    || typeof gates.scoringReady !== "boolean"
    || !Array.isArray(value.limitations)
    || value.limitations.some((item: unknown) => !nonEmptyString(item))
    || !exactArtifactSafety(value.safety)
    || !record(activity)
    || !record(activity.modelFitsByPurpose)
    || !nonnegativeInteger(activity.modelFitsByPurpose.oofFold)
    || !nonnegativeInteger(activity.modelFitsByPurpose.finalDevelopment)
    || activity.finalOotRowsAccessed !== 0
    || activity.providerCalls !== 0
    || activity.modelsPromoted !== 0
    || activity.championsMutated !== 0
  ) throw new Error("The executable-artifact summary did not preserve exact research-challenger, project, zero-promotion, and final-OOT authority.");
  const hasSelection = true;
  const artifactReady = artifact !== null && artifact.status === "EXECUTABLE_RESEARCH_ARTIFACT_MATERIALIZED";
  const jobActive = currentJob !== null && !ARTIFACT_TERMINAL.has(currentJob.status);
  if (
    gates.researchChallengerCurrent !== hasSelection
    || gates.artifactPlanReady !== (hasSelection && !jobActive && !artifactReady)
    || gates.artifactJobActive !== jobActive
    || gates.artifactReady !== artifactReady
    || gates.scoringReady !== artifactReady
    || (artifactReady && !hasSelection)
    || (currentJob !== null
      && currentJob.plan.selection.selectionDecisionId !== selection.selectionDecisionId)
  ) throw new Error("The executable-artifact readiness gates did not reconcile with the persisted selection, job, and verified artifact state.");
  return value as ProjectStage3ExecutableArtifact;
}

export async function fetchProjectStage3ExecutableArtifact(projectId: string, signal?: AbortSignal) {
  const value = await getJSON<unknown>(executableArtifactPrefix(projectId), {
    signal,
    credentials: "include",
  });
  return assertProjectStage3ExecutableArtifact(value, projectId);
}

export async function planProjectStage3ExecutableArtifact(
  projectId: string,
  payload: { selectionId?: string; nativeWorkers?: number },
  signal?: AbortSignal,
) {
  const path = `${executableArtifactPrefix(projectId)}/plan`;
  const value = await postJSON<unknown>(path, payload, signal);
  if (!record(value) || value.ok !== true || !exactArtifactPlan(value.plan, projectId)) {
    throw new Error("The executable-artifact plan response was incomplete or changed immutable scientific authority.");
  }
  if (payload.selectionId && value.plan.selection.selectionDecisionId !== payload.selectionId) {
    throw new Error("The executable-artifact plan did not bind the exact reviewed research-challenger selection.");
  }
  if (payload.nativeWorkers != null && value.plan.execution.nativeWorkers !== payload.nativeWorkers) {
    throw new Error("The executable-artifact plan did not bind the reviewed execution worker count.");
  }
  return value.plan;
}

export async function enqueueProjectStage3ExecutableArtifact(
  projectId: string,
  reviewedPlan: Pick<Stage3ExecutableArtifactPlan, "planId" | "checksum">,
  payload: { selectionId?: string; nativeWorkers?: number } = {},
  signal?: AbortSignal,
) {
  const path = `${executableArtifactPrefix(projectId)}/jobs`;
  const value = await postJSON<unknown>(path, {
    ...payload,
    expectedPlanId: reviewedPlan.planId,
    expectedPlanChecksum: reviewedPlan.checksum,
  }, signal);
  if (!record(value) || value.ok !== true || !exactArtifactJob(value.job, projectId)) {
    throw new Error("The executable-artifact job response was incomplete or violated the research safety contract.");
  }
  if (value.job.plan.planId !== reviewedPlan.planId || value.job.plan.checksum !== reviewedPlan.checksum) {
    throw new Error("The executable-artifact job did not bind the exact reviewed plan.");
  }
  return value.job;
}

export async function fetchProjectStage3ExecutableArtifactJob(
  projectId: string,
  jobId: string,
  signal?: AbortSignal,
) {
  const path = `${executableArtifactPrefix(projectId)}/jobs/${encodeURIComponent(jobId)}`;
  const value = await getJSON<unknown>(path, { signal, credentials: "include" });
  if (!record(value) || value.ok !== true || !exactArtifactJob(value.job, projectId) || value.job.jobId !== jobId) {
    throw new Error("The executable-artifact job status was incomplete or violated the research safety contract.");
  }
  return value.job;
}

export async function cancelUnstartedProjectStage3ExecutableArtifact(
  projectId: string,
  jobId: string,
  signal?: AbortSignal,
) {
  const path = `${executableArtifactPrefix(projectId)}/jobs/${encodeURIComponent(jobId)}/cancel-unstarted`;
  const value = await postJSON<unknown>(path, {}, signal);
  if (!record(value) || value.ok !== true || !exactArtifactJob(value.job, projectId) || value.job.jobId !== jobId) {
    throw new Error("The executable-artifact cancel-unstarted acknowledgement was incomplete.");
  }
  if (!["CANCEL_REQUESTED", "CANCELLED", "INTERRUPTED", "FAILED", "COMPLETE"].includes(value.job.status)) {
    throw new Error("The executable-artifact job did not acknowledge cancel-unstarted.");
  }
  return value.job;
}

const gameScoringPrefix = (projectId: string) =>
  `/projects/${encodeURIComponent(projectId)}/sports/stage3-game-scoring`;

export async function fetchProjectStage3GameScoring(projectId: string, signal?: AbortSignal) {
  const value = await getJSON<unknown>(gameScoringPrefix(projectId), {
    signal,
    credentials: "include",
  });
  return assertProjectStage3GameScoring(value, projectId);
}

export async function enqueueProjectStage3GameScoring(
  projectId: string,
  payload: Stage3GameScoringJob["request"],
  signal?: AbortSignal,
) {
  if (!exactGameScoringRequest(payload)) {
    throw new Error("The governed-game scoring request must bind one or more unique games, a verified artifact, 32–1,000,000 draws, and a nonnegative seed.");
  }
  const path = `${gameScoringPrefix(projectId)}/jobs`;
  const value = await postJSON<unknown>(path, payload, signal);
  if (!record(value) || value.ok !== true || !exactGameScoringJob(value.job, projectId)) {
    throw new Error("The governed-game scoring job response was incomplete or contained an unverified result.");
  }
  if (value.job.request.artifactId !== payload.artifactId
    || value.job.request.draws !== payload.draws
    || value.job.request.seed !== payload.seed
    || value.job.request.gameIds.length !== payload.gameIds.length
    || value.job.request.gameIds.some((gameId: string, index: number) => gameId !== payload.gameIds[index])) {
    throw new Error("The governed-game scoring job did not bind the exact reviewed request.");
  }
  return value.job;
}

export async function fetchProjectStage3GameScoringJob(
  projectId: string,
  jobId: string,
  signal?: AbortSignal,
) {
  const path = `${gameScoringPrefix(projectId)}/jobs/${encodeURIComponent(jobId)}`;
  const value = await getJSON<unknown>(path, { signal, credentials: "include" });
  if (!record(value) || value.ok !== true || !exactGameScoringJob(value.job, projectId) || value.job.jobId !== jobId) {
    throw new Error("The governed-game scoring job status was incomplete or contained an unverified result.");
  }
  return value.job;
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
