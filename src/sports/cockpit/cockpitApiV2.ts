// Phase 7D.4 (B9 / Gate 9) — the STRICT, versioned V2 response contracts for the four scientific cockpit
// reads (Active Candidate / Evaluation / Calibration / Registry-Evidence) and the V2-only feature-family
// comparison. These mirror the backend Pydantic DTOs in server/sports_cockpit/cockpit_dtos.py EXACTLY. The
// cockpit reads these shapes and no legacy/nested field paths — there is one scientific response shape.
// 2025 never appears in any of them.

export type AggregateMetricsV2 = {
  logLoss: number;
  brierScore: number;
  topLabelEce: number;
  top1Accuracy: number;
  macroF1: number;
};

export type PerClassEntryV2 = { support: number; recall: number } & Record<string, number>;
export type PerClassBlockV2 = {
  perClass: Record<string, PerClassEntryV2>;
  classwiseBrier: Record<string, number>;
  classwiseEce: Record<string, number>;
};
export type ConfusionBlockV2 = {
  confusionMatrix: number[][];
  axes: Record<string, string>;
  classOrder: string[];
};
export type ReliabilityBinV2 = { meanConfidence: number | null; accuracy: number | null; count: number };
export type ClasswiseReliabilityBinV2 = { meanProbability: number | null; realizedFrequency: number | null; count: number };
export type ReliabilityBlockV2 = {
  topLabelReliability: ReliabilityBinV2[];
  classwiseReliability: Record<string, ClasswiseReliabilityBinV2[]>;
  probabilityHistograms?: unknown;
};

export type ActiveCandidateResponseV2 = {
  schemaVersion: "ACTIVE_CANDIDATE_RESPONSE_V2";
  status: string;
  runId: string;
  runAuthorityId: string;
  datasetVersionId: string;
  generation: string;
  modelFamily: string;
  developmentSeasons: number[];
  developmentRows: number;
  validationSeason: number;
  validationRows: number;
  runReceiptSha256: string;
  bundleManifestSha256: string;
  bindingId: string;
  bindingRevision: number;
  activationRevision: number;
  activatedAt: string;
  preprocessingContractId: string;
};

export type ModelEvaluationResponseV2 = {
  schemaVersion: "MODEL_EVALUATION_RESPONSE_V2";
  runId: string;
  runAuthorityId: string;
  runReceiptSha256: string;
  bundleManifestSha256: string;
  datasetVersionId: string;
  datasetContentSha256: string;
  generation: string;
  modelFamily: string;
  developmentSeasons: number[];
  developmentRows: number;
  validationSeason: number;
  validationRows: number;
  featureCount: number;
  preprocessingContractId: string;
  classOrder: string[];
  metrics: AggregateMetricsV2;
  perClass: PerClassBlockV2;
  confusion: ConfusionBlockV2;
  diagnostics: ReliabilityBlockV2;
  independentRecomputedLogLoss: number;
  recomputationMatchesStored: boolean;
  calibrationStatus: string;
  calibratorConfigured: boolean;
  validationLabel: string;
};

export type ModelCalibrationResponseV2 = {
  schemaVersion: "MODEL_CALIBRATION_RESPONSE_V2";
  runId: string;
  runReceiptSha256: string;
  bundleManifestSha256: string;
  generation: string;
  modelFamily: string;
  validationSeason: number;
  calibrationStatus: string;
  calibratorConfigured: boolean;
  topLabelEce: number;
  brierScore: number;
  classOrder: string[];
  topLabelReliability: ReliabilityBinV2[];
  classwiseReliability: Record<string, ClasswiseReliabilityBinV2[]>;
  validationLabel: string;
};

export type ModelRegistryEvidenceResponseV2 = {
  schemaVersion: "MODEL_REGISTRY_EVIDENCE_RESPONSE_V2";
  runId: string;
  runAuthorityId: string;
  runReceiptSha256: string;
  bundleManifestSha256: string;
  datasetVersionId: string;
  datasetContentSha256: string;
  generation: string;
  modelFamily: string;
  preprocessorSha256: string;
  modelSha256: string;
  predictionSha256: string;
  aggregateMetricsSha256: string;
  codeRevision: string;
  worktreeContentSha256: string;
  environmentSha256: string;
  developmentSeasons: number[];
  developmentRows: number;
  validationSeason: number;
  validationRows: number;
  featureCount: number;
  logLoss: number;
  independentRecomputedLogLoss: number;
  recomputationMatchesStored: boolean;
  calibrationStatus: string;
  validationLabel: string;
};

export type ComparisonArmV2 = {
  runId: string;
  runReceiptSha256: string;
  bundleManifestSha256: string;
  featureSetName: string;
  featureSetSha256: string;
  metrics: AggregateMetricsV2;
};
export type FeatureFamilyComparisonResponseV2 = {
  schemaVersion: "MODEL_FEATURE_FAMILY_COMPARISON_RECEIPT_V1";
  comparisonReceiptSha256: string;
  projectId: string;
  bindingId: string;
  bindingRevision: number;
  generation: string;
  datasetVersionId: string;
  datasetContentSha256: string;
  modelFamily: string;
  seed: number;
  controlFeatureSet: string;
  challengerFeatureSet: string;
  featureFamilyAdded: string[];
  featureFamilyId: string;
  featureFamilySha256: string;
  control: ComparisonArmV2;
  challenger: ComparisonArmV2;
  validationSeason: number;
  validationRows: number;
  metricDelta: Record<string, number>;
  classConditionalLogLossDelta: Record<string, number>;
  uncertainty: {
    method: string;
    iterations: number;
    games: number;
    logLossDeltaMean: number;
    logLossDelta95CI: number[];
    challengerImproves: boolean;
  };
  createdAt: string;
};

// One place that fixes the exact endpoint paths for the V2 scientific reads.
export const gen3V2Paths = {
  activeCandidate: (projectId: string) => `/cockpit/gen3/active-candidate/${encodeURIComponent(projectId)}`,
  evaluation: (projectId: string) => `/cockpit/gen3/evaluation/${encodeURIComponent(projectId)}`,
  calibration: (projectId: string) => `/cockpit/gen3/calibration/${encodeURIComponent(projectId)}`,
  registryEvidence: (projectId: string) => `/cockpit/gen3/registry-evidence/${encodeURIComponent(projectId)}`,
};
