import { useCallback, useEffect, useState } from "react";
import { BASE } from "../lib/api";

export type SportsDatasetTotals = {
  packageFiles: number;
  parquetFiles: number;
  rows: number;
  parquetBytes: number;
  games: number;
  plateAppearances: number;
  transitions: number;
  starterTargets: number;
  bullpenAppearances: number;
  playerPriors: number;
  partitions: number;
  playerIdentityCoverage: number;
};

export type SportsDatasetFamily = { family: string; rows: number };
export type SportsSeasonCoverage = {
  season: number;
  games: number;
  plateAppearances: number;
  transitions: number;
  starterTargets: number;
  bullpenAppearances: number;
};
export type SportsPopulation = {
  populationId: string;
  rows: number;
  predicate: string;
  uses: string[];
  prohibitions: string[];
};
export type SportsTemporalFold = {
  foldId: string;
  trainingSeasons: number[];
  validationSeason: number;
  trainingRows: number;
  validationRows: number;
};
export type SportsEvidenceCoverage = {
  evidence: string;
  status: string;
  detail?: string;
};
export type SportsSourceRight = {
  source: string;
  status?: string;
  attribution?: string;
  allowedUses?: string[];
  prohibitedUses?: string[];
};
export type SportsProjectStage = {
  stepId?: string;
  number?: number;
  title?: string;
  status: string;
  evidence?: string[];
};
export type SportsFeatureAuditSeason = {
  season: number;
  plateAppearanceRows: number;
  eligibleBattingPriorRows: number;
  eligiblePitchingPriorRows: number;
  batterYMinus1JoinMatches: number;
  batterYMinus1JoinDenominator: number;
  pitcherYMinus1JoinMatches: number;
  pitcherYMinus1JoinDenominator: number;
};
export type SportsFeatureAudit = {
  contractVersion: string;
  status: string;
  method: string;
  observedNamespaces: {
    plateAppearance: string[];
    playerPrior: string[];
  };
  perSeasonRows: SportsFeatureAuditSeason[];
  joinEvidence: {
    batterMatches: number;
    batterDenominator: number;
    pitcherMatches: number;
    pitcherDenominator: number;
    inferenceOrFuzzyMatchingUsed: boolean;
    sameSeasonPredictorEligibleObserved: boolean;
    plateAppearanceCanonicalIdentityResolvedObserved: boolean;
  };
  missingBridge: {
    isMissing: boolean;
    requiredArtifact: string;
    reason: string;
  };
  auditedAt?: string;
};

export type SportsIdentityBridgeEvidenceRow = Record<string, unknown>;

export type SportsIdentityBridgeTotals = {
  packageFiles: number;
  packageBytes: number;
  aliasRows: number;
  portablePlayers: number;
  governedPlayers: number;
  primaryPortablePlayers: number;
  primaryGovernedPlayers: number;
  namespaces: number;
  joinContracts: number;
  joinReferences: number;
};

export type SportsIdentityBridgeJoinAudit = {
  artifactId: string;
  artifactSha: string;
  logicalUri: string;
  status: string;
  totalReferences: number;
  resolvedReferences: number;
  mappingRate: number;
  unresolvedReferences: number;
  ambiguousReferences: number;
  multiplyMappedReferences: number;
  joins: SportsIdentityBridgeEvidenceRow[];
};

export type SportsIdentityBridgeRights = {
  status: string;
  allowedPurposes: string[];
  prohibitedPurposes: string[];
};

export type SportsIdentityBridge = {
  registrationId: string;
  contractName: string;
  contractVersion: string;
  manifestId: string;
  manifestSha: string;
  packageId: string;
  parentRegistrationId: string;
  parentManifestSha: string;
  parentPartitionAuthoritySha: string;
  aliasAuthoritySha: string;
  dimensionAuthoritySha: string;
  validationReportSha: string;
  logicalRoot: string;
  validationStatus: string;
  registeredAt: string;
  active: boolean;
  totals: SportsIdentityBridgeTotals;
  namespaceEvidence: SportsIdentityBridgeEvidenceRow[];
  joinAudit: SportsIdentityBridgeJoinAudit;
  yMinus1Coverage: SportsIdentityBridgeEvidenceRow[];
  rights: SportsIdentityBridgeRights;
  limitations: string[];
  noNamesOrFuzzyMatching: boolean;
};

export const SPORTS_PA_TERMINAL_STATUSES = [
  "RESEARCH_CHALLENGER",
  "RESEARCH_BASELINE",
  "REJECTED_BASELINE",
  "BLOCKED",
] as const;

export type SportsPaTerminalStatus = typeof SPORTS_PA_TERMINAL_STATUSES[number];
export type SportsPaEvidenceRecord = Record<string, unknown>;

export type SportsPaMetrics = SportsPaEvidenceRecord & {
  schemaVersion?: string;
  classOrder: string[];
  rowCount?: number;
  binCount?: number;
  logLoss?: number;
  brierScore?: number;
  topLabelEce?: number;
  top1Accuracy?: number;
  balancedAccuracy?: number;
  macroF1?: number;
  weightedF1?: number;
  perClass: Record<string, SportsPaEvidenceRecord>;
  confusionMatrix: number[][];
  realizedPrevalence: Record<string, number>;
  predictedPrevalence: Record<string, number>;
  argmaxPrevalence: Record<string, number>;
  topLabelReliability: SportsPaEvidenceRecord[];
  classwiseReliability: Record<string, SportsPaEvidenceRecord[]>;
  probabilityHistograms: Record<string, SportsPaEvidenceRecord[]>;
};

export type SportsPaFold = {
  foldId: string;
  status: string;
  validationSeason?: number;
  trainSeasons: number[];
  trainingRows?: number;
  validationRows?: number;
  rowCount?: number;
  metrics?: SportsPaMetrics;
  rawMetrics?: SportsPaMetrics;
  calibratedMetrics?: SportsPaMetrics;
  predictionArtifact?: SportsPaEvidenceRecord;
};

export type SportsPaCandidate = {
  candidateId: string;
  name: string;
  definition: string;
  candidateType: string;
  ordinal?: number;
  status: string;
  selected: boolean;
  eligible?: boolean;
  rejectionReasons: string[];
  hyperparameters: SportsPaEvidenceRecord;
  aggregateMetrics?: SportsPaMetrics;
  aggregateEvidence: SportsPaEvidenceRecord;
  convergence?: unknown;
  runtimeSeconds?: number;
  folds: SportsPaFold[];
};

export type SportsPaFeatureView = {
  featureViewId: string;
  contractVersion: string;
  contractSha: string;
  contentSha: string;
  logicalRoot: string;
  artifactSha: string;
  artifactBytes?: number;
  rowCount?: number;
  classOrder: string[];
  seasonRows: SportsPaEvidenceRecord[];
  features: unknown[];
  artifacts: SportsPaEvidenceRecord[];
};

export type SportsPaExperiment = {
  experimentId: string;
  status: string;
  objective: string;
  seed?: number;
  trainingContractVersion: string;
  startedAt: string;
  completedAt: string;
  durationSeconds?: number;
  tuningPolicy?: unknown;
};

export type SportsPaCalibration = {
  status: string;
  sourceSeason?: number;
  retained?: boolean;
  fittedTemperature?: number;
  retainedTemperature?: number;
  reason: string;
  raw2024?: SportsPaMetrics;
  scaled2024?: SportsPaMetrics;
  raw2025?: SportsPaMetrics;
  scaled2025?: SportsPaMetrics;
  final2025?: SportsPaMetrics;
};

export type SportsPaBootstrapComparison = {
  comparatorCandidateId: string;
  comparatorName: string;
  foldId: string;
  validationSeason?: number;
  resampleCount?: number;
  seed?: number;
  logLossDifference: SportsPaEvidenceRecord;
  brierScoreDifference: SportsPaEvidenceRecord;
};

export type SportsPaRegistry = {
  modelId: string;
  artifactId: string;
  status: string;
  logicalUri: string;
  registeredAt: string;
  lastValidatedAt: string;
  active?: boolean;
  artifacts: SportsPaEvidenceRecord[];
};

export type SportsPaGraph = {
  graphId?: string;
  parentGraphId?: string;
  status: string;
  nodes: SportsPaEvidenceRecord[];
  edges: SportsPaEvidenceRecord[];
};

export type SportsPaBaseline = {
  schemaVersion: string;
  runId: string;
  runSha: string;
  projectId: string;
  status: string;
  decision: string;
  decisionReason: string;
  parent?: SportsPaEvidenceRecord;
  identityBridge?: SportsPaEvidenceRecord;
  classOrder: string[];
  featureView?: SportsPaFeatureView;
  experiment?: SportsPaExperiment;
  candidates: SportsPaCandidate[];
  selectedCandidateId: string;
  selected?: SportsPaEvidenceRecord;
  selectedHyperparameters: SportsPaEvidenceRecord;
  calibration?: SportsPaCalibration;
  bootstrapComparisons: SportsPaBootstrapComparison[];
  registry?: SportsPaRegistry;
  artifacts: SportsPaEvidenceRecord[];
  graph?: SportsPaGraph;
  limitations: string[];
};

export const SPORTS_PHASE4_COMPONENT_TYPES = [
  "DYNAMIC_PLAYER_STATE",
  "LINEUP_PROJECTION",
  "STARTER_DURATION",
  "BULLPEN_USAGE",
] as const;

export type SportsPhase4ComponentType = typeof SPORTS_PHASE4_COMPONENT_TYPES[number];
export type SportsPhase4EvidenceRecord = Record<string, unknown>;

export type SportsPhase4Artifact = {
  artifactId: string;
  componentId: string;
  artifactType: string;
  logicalUri: string;
  sha256: string;
  byteCount?: number;
  mediaType: string;
};

export type SportsPhase4Component = {
  componentId: string;
  componentType: SportsPhase4ComponentType;
  contractName: string;
  contractSha: string;
  status: string;
  decisionReason: string;
  descriptor: SportsPhase4EvidenceRecord;
  candidates: SportsPhase4EvidenceRecord[];
  selected?: SportsPhase4EvidenceRecord;
  folds: SportsPhase4EvidenceRecord[];
  metrics: SportsPhase4EvidenceRecord;
  calibration?: SportsPhase4EvidenceRecord;
  bootstrap: SportsPhase4EvidenceRecord[];
  coverage: SportsPhase4EvidenceRecord;
  limitations: string[];
  artifactIds: string[];
  artifacts: SportsPhase4Artifact[];
};

export const SPORTS_CATCHER_READINESS_STATUSES = [
  "CATCHER_INFLUENCE_READY_FOR_RESEARCH_DESIGN",
  "CATCHER_INFLUENCE_PARTIALLY_READY",
  "CATCHER_INFLUENCE_DATA_AUDIT_BLOCKED",
] as const;

export type SportsCatcherReadinessStatus = typeof SPORTS_CATCHER_READINESS_STATUSES[number];

// Data-availability audit evidence only — never a catcher score, ranking, or model
// performance metric. Sub-objects are sanitized generic records rendered as
// read-only evidence; the frontend never fabricates any of these values.
export type SportsCatcherReadiness = {
  contractName: string;
  terminalStatus: string;
  rationale: string;
  seasons: number[];
  startingCatcherCoverage: SportsPhase4EvidenceRecord;
  paCatcherAssignmentCoverage: SportsPhase4EvidenceRecord;
  batterySampleDistribution: SportsPhase4EvidenceRecord;
  batteryFallbackLevels: SportsPhase4EvidenceRecord;
  catcherBatterSampleDistribution: SportsPhase4EvidenceRecord;
  freeFeatureInventory: SportsPhase4EvidenceRecord[];
  premiumDataGaps: SportsPhase4EvidenceRecord[];
  limitations: string[];
};

// E1 pitch-sequence process feature materialization readiness (not a model).
export type SportsPitchSequenceFeatures = {
  terminalStatus: string;
  parserVersion: string;
  seasons: number[];
  trailingWindowDays?: number;
  batterFeatureCount?: number;
  pitcherFeatureCount?: number;
  totalFeatureCount?: number;
  rowsRead?: number;
  rowsMaterialized?: number;
  materializationId: string;
  parseQuality: SportsPhase4EvidenceRecord;
  parserCategories: SportsPhase4EvidenceRecord[];
  coverage: SportsPhase4EvidenceRecord;
  earlySeasonMissing: SportsPhase4EvidenceRecord;
  featureSummary: SportsPhase4EvidenceRecord[];
  strikeoutWalkReadiness: SportsPhase4EvidenceRecord;
  rareOutcomeLimitations: string[];
  limitations: string[];
};

// E2 batter × pitcher process interaction feature materialization (not a model).
export type SportsProcessInteractions = {
  terminalStatus: string;
  seasons: number[];
  featureCount?: number;
  featureHardMax?: number;
  materializationId: string;
  parentE1: SportsPhase4EvidenceRecord;
  interactionFamilies: SportsPhase4EvidenceRecord;
  features: string[];
  coverage: SportsPhase4EvidenceRecord;
  redundancy: SportsPhase4EvidenceRecord;
  strikeoutWalkReadiness: SportsPhase4EvidenceRecord;
  rowsRead?: number;
  rowsMaterialized?: number;
  limitations: string[];
};

// E1/E2 incremental-signal feature-ablation research study (NOT a promoted model).
export type SportsIncrementalSignalStudy = {
  studyId: string;
  contractName: string;
  researchOnly: boolean;
  promotedModel: boolean;
  changesChampionStatus: boolean;
  modelPolicy: SportsPhase4EvidenceRecord;
  population: SportsPhase4EvidenceRecord;
  branchFeatureCounts: SportsPhase4EvidenceRecord;
  anchor: SportsPhase4EvidenceRecord;
  incrementalRows: SportsPhase4EvidenceRecord[];
  practicalBandDefinition: SportsPhase4EvidenceRecord;
  strikeout: SportsPhase4EvidenceRecord;
  walkHbpCi: SportsPhase4EvidenceRecord;
  bootstrap: SportsPhase4EvidenceRecord[];
  decision: SportsPhase4EvidenceRecord;
  nextStep: SportsPhase4EvidenceRecord;
  limitations: string[];
};

// E1/E2 severe-miss forensic study (analysis only — no promoted model, population preserved).
export type SportsSevereMissForensics = {
  studyId: string;
  contractName: string;
  researchOnly: boolean;
  officialPopulationPreserved: boolean;
  population: SportsPhase4EvidenceRecord;
  anchor: SportsPhase4EvidenceRecord;
  pareto2025: SportsPhase4EvidenceRecord[];
  tailSensitivity2025: SportsPhase4EvidenceRecord;
  overIndex2025: SportsPhase4EvidenceRecord;
  confusionPairs2025: SportsPhase4EvidenceRecord[];
  severeMissClassifier: SportsPhase4EvidenceRecord;
  randomness: SportsPhase4EvidenceRecord;
  topThreePatterns: SportsPhase4EvidenceRecord[];
  recommendedNextStep: string;
  limitations: string[];
};

// Phase 5 deterministic game-replay engine (mechanical, not a predictive/probabilistic simulator).
export type SportsGameReplay = {
  replayRunId: string;
  contractName: string;
  researchOnly: boolean;
  probabilisticSimulation: boolean;
  readinessStatus: string;
  seasons: number[];
  sourceFamily: string;
  fullExecuted: boolean;
  gamesAttempted?: number;
  classificationCounts: SportsPhase4EvidenceRecord;
  exactReplayRate?: number;
  finalScoreExactRate?: number;
  inningSequenceExactRate?: number;
  zeroContinuityRate?: number;
  mismatchesByCategory: SportsPhase4EvidenceRecord;
  mismatchForensics: SportsPhase4EvidenceRecord[];
  limitations: string[];
};

// Phase 5B empirical base-out / runner-advancement transition model (simulation component).
export type SportsBaseOutTransition = {
  transitionRunId: string;
  contractName: string;
  readinessStatus: string;
  researchOnly: boolean;
  parentReplayAuthority: SportsPhase4EvidenceRecord;
  retainedPolicy: string;
  devSeasons: number[];
  developmentRows?: number;
  primaryStateCells?: number;
  sparseCellCount?: number;
  deterministicRules: string[];
  illegalProbabilityMass?: number;
  validation2024: SportsPhase4EvidenceRecord;
  frozen2025: SportsPhase4EvidenceRecord;
  stochasticStressTest: SportsPhase4EvidenceRecord;
  reproducibility: SportsPhase4EvidenceRecord;
  modelArtifact: SportsPhase4EvidenceRecord;
  limitations: string[];
};

// Phase 5C simulation input layer (Monte-Carlo entry gates 5, 6, 7). Not a game forecast,
// betting model, or Monte-Carlo result.
export type SportsSimulationInput = {
  runId: string;
  contractName: string;
  researchOnly: boolean;
  parentAuthorities: SportsPhase4EvidenceRecord;
  readiness: SportsPhase4EvidenceRecord;
  monteCarloEntryDecision: string;
  monteCarloEntryGates: SportsPhase4EvidenceRecord;
  paProvider: SportsPhase4EvidenceRecord;
  participantProvider: SportsPhase4EvidenceRecord;
  gameInitialization: SportsPhase4EvidenceRecord;
  shortSequenceIntegration: SportsPhase4EvidenceRecord;
  eligiblePopulation: SportsPhase4EvidenceRecord;
  monteCarloPerformanceEstimate: SportsPhase4EvidenceRecord;
  limitations: string[];
};

// Phase 5D whole-game Monte Carlo research baseline (HISTORICAL_PARTICIPANTS_ORACLE_MODE).
// Not a game forecast, betting model, or market comparison.
export type SportsWholeGameMonteCarlo = {
  runId: string;
  contractName: string;
  researchOnly: boolean;
  participantMode: string;
  parentAuthorities: SportsPhase4EvidenceRecord;
  simulationsPerGame?: number;
  developmentStandardSimulations?: number;
  eligibleGames: SportsPhase4EvidenceRecord;
  convergence: SportsPhase4EvidenceRecord;
  bySeason: SportsPhase4EvidenceRecord;
  d3GameLevelValue: string;
  contactQualityPriority: string;
  participationAblationDecision: string;
  simulatorReadiness: string;
  legality: SportsPhase4EvidenceRecord;
  limitations: string[];
};

// Phase 5E projected-participation ablation (P0->P3). Research diagnostic; not a forecast,
// betting model, or market comparison.
export type SportsParticipationAblation = {
  runId: string;
  contractName: string;
  researchOnly: boolean;
  branchLabels: SportsPhase4EvidenceRecord;
  projectionAuthorities: SportsPhase4EvidenceRecord;
  simulationsPerGame?: number;
  comparableGames: SportsPhase4EvidenceRecord;
  bySeason: SportsPhase4EvidenceRecord;
  bootstrap: SportsPhase4EvidenceRecord;
  stateFallback: SportsPhase4EvidenceRecord;
  meanLineupRecall: SportsPhase4EvidenceRecord;
  overallDecision: string;
  lineupGameImpact: string;
  starterDurationGameImpact: string;
  bullpenGameImpact: string;
  remainingOracleDependencies: SportsPhase4EvidenceRecord;
  limitations: string[];
};

export type SportsPhase4Study = {
  schemaVersion: string;
  studyId: string;
  studySha: string;
  projectId: string;
  createdAt: string;
  codeRevision: string;
  dataset: SportsPhase4EvidenceRecord;
  identityBridge: SportsPhase4EvidenceRecord;
  phase3Baseline: SportsPhase4EvidenceRecord;
  components: Partial<Record<"dynamicState" | "lineup" | "starterDuration" | "bullpenUsage", SportsPhase4Component>>;
  artifacts: SportsPhase4Artifact[];
  graph?: SportsPaGraph;
  decision: SportsPhase4EvidenceRecord;
  limitations: string[];
  registeredAt: string;
  lastValidatedAt: string;
  active?: boolean;
  catcherReadiness?: SportsCatcherReadiness;
  pitchSequenceFeatures?: SportsPitchSequenceFeatures;
  processInteractions?: SportsProcessInteractions;
  incrementalSignalStudy?: SportsIncrementalSignalStudy;
  severeMissForensics?: SportsSevereMissForensics;
  gameReplay?: SportsGameReplay;
  baseOutTransition?: SportsBaseOutTransition;
  simulationInput?: SportsSimulationInput;
  wholeGameMonteCarlo?: SportsWholeGameMonteCarlo;
  participationAblation?: SportsParticipationAblation;
};

export type RegisteredSportsProject = {
  projectId: string;
  name: string;
  status?: string;
  sport?: string;
  league?: string;
  developmentPeriod?: string;
  priorHistory?: string;
  primaryTarget?: string;
  secondaryTargets?: string[];
  forecastLifecycle?: string;
  baselinePopulation?: string;
  upperBoundPopulation?: string;
  researchPurpose?: string;
  workflowId?: string;
  stages?: SportsProjectStage[];
  featureAudit?: SportsFeatureAudit;
};

export type ActiveSportsDataset = {
  registrationId: string;
  datasetId: string;
  datasetVersionId: string;
  manifestId: string;
  manifestSha: string;
  partitionAuthoritySha?: string;
  packageId: string;
  sport: string;
  league: string;
  evidenceCutoff: string;
  publishedAt: string;
  logicalRoot: string;
  validationStatus: string;
  registeredAt: string;
  rightsStatus: string;
  limitationCount: number;
  active: boolean;
  seasons: number[];
  totals: SportsDatasetTotals;
  families: SportsDatasetFamily[];
  seasonCoverage: SportsSeasonCoverage[];
  populations: SportsPopulation[];
  folds: SportsTemporalFold[];
  evidenceCoverage: SportsEvidenceCoverage[] | Record<string, string | boolean | number>;
  rights: SportsSourceRight[];
  limitations: string[];
  project?: RegisteredSportsProject;
  featureAudit?: SportsFeatureAudit;
  identityBridge?: SportsIdentityBridge;
  paBaseline?: SportsPaBaseline;
  phase4?: SportsPhase4Study;
};

type EvidenceState<T> =
  | { status: "loading"; data: null; error: null }
  | { status: "ready"; data: T; error: null }
  | { status: "empty"; data: null; error: null }
  | { status: "error"; data: null; error: string };

export type RefreshableEvidenceState<T> = EvidenceState<T> & { refresh: () => void };

const initialEvidenceState = { status: "loading", data: null, error: null } as const;
const rawEnv = (import.meta as any)?.env ?? {};
const devUserId = rawEnv.DEV ? String(rawEnv.VITE_ATLAS_DEV_USER_ID || "local-dev-user") : "";

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function publicErrorMessage(payload: unknown, fallback: string) {
  if (!isRecord(payload)) return fallback;
  if (typeof payload.detail === "string") return payload.detail;
  if (isRecord(payload.detail)) {
    const code = typeof payload.detail.code === "string" ? payload.detail.code : "VALIDATION_FAILED";
    const message = typeof payload.detail.message === "string" ? payload.detail.message : fallback;
    return `${code}: ${message}`;
  }
  return typeof payload.error === "string" ? payload.error : fallback;
}

const MLB_PROJECT_STAGE_MAP: Record<string, { number: number; stepId: string; title: string }> = {
  objective_forecast_contract: { number: 1, stepId: "mlb-01", title: "Project & Forecast Contract" },
  data_evidence_manifest: { number: 2, stepId: "mlb-02", title: "Baseball Data Evidence" },
  identity_coverage_leakage: { number: 3, stepId: "mlb-03", title: "Identity, Coverage & Leakage" },
  player_team_state: { number: 4, stepId: "mlb-04", title: "Hitter & Pitcher State" },
  participation_usage: { number: 5, stepId: "mlb-05", title: "Lineup, Starter & Bullpen Usage" },
  event_models: { number: 6, stepId: "mlb-06", title: "Plate-Appearance Models" },
  game_simulation: { number: 7, stepId: "mlb-07", title: "Base-Out Game Simulation" },
  candidate_models_experiments: { number: 8, stepId: "mlb-08", title: "Candidate Model Laboratory" },
  temporal_validation: { number: 9, stepId: "mlb-09", title: "Temporal Validation" },
  calibration_reliability: { number: 10, stepId: "mlb-10", title: "Calibration & Reliability" },
  model_graph_decision: { number: 11, stepId: "mlb-11", title: "Model Graph & Decision" },
  export_to_asp: { number: 12, stepId: "mlb-12", title: "Export MLB Bundle" },
};

function stringArray(value: unknown) {
  return Array.isArray(value) ? value.map(String) : [];
}

function finiteNumber(value: unknown) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : 0;
}

function isPhysicalReference(value: string) {
  return /(?:^|[\s"'([{=])file:/i.test(value)
    || /(?:^|[\s"'([{=\\/])[a-z]:[\\/]/i.test(value)
    || /(?:^|[\s"'([{=])\\\\/.test(value)
    || /(?:^|[\s"'([{=])\//.test(value);
}

function publicString(value: unknown, fallback = "") {
  if (typeof value !== "string" || !value) return fallback;
  return isPhysicalReference(value) ? "Target-local reference withheld" : value;
}

function publicStringArray(value: unknown) {
  return Array.isArray(value) ? value.map((item) => publicString(String(item))).filter(Boolean) : [];
}

function sanitizePublicEvidenceValue(value: unknown): unknown {
  if (typeof value === "string") return publicString(value);
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "boolean" || value === null) return value;
  if (Array.isArray(value)) return value.map(sanitizePublicEvidenceValue);
  if (isRecord(value)) {
    return Object.fromEntries(Object.entries(value)
      .filter(([key]) => !/(?:physical|filesystem|absolute)(?:path|root|uri)?|(?:file|source|package)path/i.test(key))
      .map(([key, item]) => [key, sanitizePublicEvidenceValue(item)]));
  }
  return null;
}

function normalizePublicEvidenceRows(value: unknown): SportsIdentityBridgeEvidenceRow[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!isRecord(item)) return [];
    return [sanitizePublicEvidenceValue(item) as SportsIdentityBridgeEvidenceRow];
  });
}

function normalizeIdentityBridge(value: unknown): SportsIdentityBridge | undefined {
  if (!isRecord(value)) return undefined;
  const registrationId = publicString(value.registrationId);
  const contractVersion = publicString(value.contractVersion);
  if (!registrationId || !contractVersion) return undefined;
  const totals = isRecord(value.totals) ? value.totals : {};
  const joinAudit = isRecord(value.joinAudit) ? value.joinAudit : {};
  const rights = isRecord(value.rights) ? value.rights : {};
  return {
    registrationId,
    contractName: publicString(value.contractName, "SPORTS_IDENTITY_BRIDGE"),
    contractVersion,
    manifestId: publicString(value.manifestId),
    manifestSha: publicString(value.manifestSha),
    packageId: publicString(value.packageId),
    parentRegistrationId: publicString(value.parentRegistrationId),
    parentManifestSha: publicString(value.parentManifestSha),
    parentPartitionAuthoritySha: publicString(value.parentPartitionAuthoritySha),
    aliasAuthoritySha: publicString(value.aliasAuthoritySha),
    dimensionAuthoritySha: publicString(value.dimensionAuthoritySha),
    validationReportSha: publicString(value.validationReportSha),
    logicalRoot: publicString(value.logicalRoot),
    validationStatus: publicString(value.validationStatus, "UNKNOWN"),
    registeredAt: publicString(value.registeredAt),
    active: value.active === true,
    totals: {
      packageFiles: finiteNumber(totals.packageFiles),
      packageBytes: finiteNumber(totals.packageBytes),
      aliasRows: finiteNumber(totals.aliasRows),
      portablePlayers: finiteNumber(totals.portablePlayers),
      governedPlayers: finiteNumber(totals.governedPlayers),
      primaryPortablePlayers: finiteNumber(totals.primaryPortablePlayers),
      primaryGovernedPlayers: finiteNumber(totals.primaryGovernedPlayers),
      namespaces: finiteNumber(totals.namespaces),
      joinContracts: finiteNumber(totals.joinContracts),
      joinReferences: finiteNumber(totals.joinReferences),
    },
    namespaceEvidence: normalizePublicEvidenceRows(value.namespaceEvidence),
    joinAudit: {
      artifactId: publicString(joinAudit.artifactId),
      artifactSha: publicString(joinAudit.artifactSha),
      logicalUri: publicString(joinAudit.logicalUri),
      status: publicString(joinAudit.status, "UNKNOWN"),
      totalReferences: finiteNumber(joinAudit.totalReferences),
      resolvedReferences: finiteNumber(joinAudit.resolvedReferences),
      mappingRate: finiteNumber(joinAudit.mappingRate),
      unresolvedReferences: finiteNumber(joinAudit.unresolvedReferences),
      ambiguousReferences: finiteNumber(joinAudit.ambiguousReferences),
      multiplyMappedReferences: finiteNumber(joinAudit.multiplyMappedReferences),
      joins: normalizePublicEvidenceRows(joinAudit.joins),
    },
    yMinus1Coverage: normalizePublicEvidenceRows(value.yMinus1Coverage),
    rights: {
      status: publicString(rights.status, "UNKNOWN"),
      allowedPurposes: publicStringArray(rights.allowedPurposes),
      prohibitedPurposes: publicStringArray(rights.prohibitedPurposes),
    },
    limitations: publicStringArray(value.limitations),
    noNamesOrFuzzyMatching: value.noNamesOrFuzzyMatching === true,
  };
}

export function sportsPaDecisionStatus(value: unknown): SportsPaTerminalStatus | null {
  const normalized = String(value || "").trim().toUpperCase();
  return SPORTS_PA_TERMINAL_STATUSES.includes(normalized as SportsPaTerminalStatus)
    ? normalized as SportsPaTerminalStatus
    : null;
}

export function sportsIdentityBridgeIsValidated(bridge: SportsIdentityBridge | undefined) {
  const validStatuses = new Set(["VALID", "VALIDATED", "COMPLETE", "COMPLETED", "PASSED"]);
  return Boolean(
    bridge?.active
    && bridge.noNamesOrFuzzyMatching
    && validStatuses.has(bridge.validationStatus.toUpperCase())
    && validStatuses.has(bridge.joinAudit.status.toUpperCase()),
  );
}

function optionalFiniteNumber(value: unknown) {
  if (value === null || value === undefined || value === "") return undefined;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : undefined;
}

function numberArray(value: unknown) {
  return Array.isArray(value)
    ? value.flatMap((item) => {
        const numeric = optionalFiniteNumber(item);
        return numeric === undefined ? [] : [numeric];
      })
    : [];
}

function normalizePublicEvidenceRecord(value: unknown): SportsPaEvidenceRecord {
  return isRecord(value)
    ? sanitizePublicEvidenceValue(value) as SportsPaEvidenceRecord
    : {};
}

function optionalPublicEvidenceRecord(value: unknown): SportsPaEvidenceRecord | undefined {
  return isRecord(value) ? normalizePublicEvidenceRecord(value) : undefined;
}

function normalizePublicEvidenceRecords(value: unknown): SportsPaEvidenceRecord[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (isRecord(item)) return [normalizePublicEvidenceRecord(item)];
    const sanitized = sanitizePublicEvidenceValue(item);
    return sanitized === null ? [] : [{ value: sanitized }];
  });
}

function normalizePublicEvidenceItems(value: unknown) {
  return Array.isArray(value)
    ? value.map(sanitizePublicEvidenceValue).filter((item) => item !== null)
    : [];
}

function normalizeNumberRecord(value: unknown): Record<string, number> {
  if (!isRecord(value)) return {};
  return Object.fromEntries(Object.entries(value).flatMap(([key, item]) => {
    const numeric = optionalFiniteNumber(item);
    return numeric === undefined ? [] : [[key, numeric]];
  }));
}

function normalizeEvidenceRecordMap(value: unknown): Record<string, SportsPaEvidenceRecord> {
  if (!isRecord(value)) return {};
  return Object.fromEntries(Object.entries(value).flatMap(([key, item]) => (
    isRecord(item) ? [[key, normalizePublicEvidenceRecord(item)]] : []
  )));
}

function normalizeEvidenceRowsMap(value: unknown): Record<string, SportsPaEvidenceRecord[]> {
  if (!isRecord(value)) return {};
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, normalizePublicEvidenceRecords(item)]));
}

function normalizeConfusionMatrix(value: unknown) {
  if (!Array.isArray(value)) return [];
  return value.flatMap((row) => Array.isArray(row) ? [numberArray(row)] : []);
}

function normalizePaMetrics(value: unknown): SportsPaMetrics | undefined {
  if (!isRecord(value)) return undefined;
  const sanitized = normalizePublicEvidenceRecord(value);
  return {
    ...sanitized,
    schemaVersion: typeof value.schemaVersion === "string" ? publicString(value.schemaVersion) : undefined,
    classOrder: publicStringArray(value.classOrder),
    rowCount: optionalFiniteNumber(value.rowCount),
    binCount: optionalFiniteNumber(value.binCount),
    logLoss: optionalFiniteNumber(value.logLoss),
    brierScore: optionalFiniteNumber(value.brierScore),
    topLabelEce: optionalFiniteNumber(value.topLabelEce),
    top1Accuracy: optionalFiniteNumber(value.top1Accuracy),
    balancedAccuracy: optionalFiniteNumber(value.balancedAccuracy),
    macroF1: optionalFiniteNumber(value.macroF1),
    weightedF1: optionalFiniteNumber(value.weightedF1),
    perClass: normalizeEvidenceRecordMap(value.perClass),
    confusionMatrix: normalizeConfusionMatrix(value.confusionMatrix),
    realizedPrevalence: normalizeNumberRecord(value.realizedPrevalence),
    predictedPrevalence: normalizeNumberRecord(value.predictedPrevalence),
    argmaxPrevalence: normalizeNumberRecord(value.argmaxPrevalence),
    topLabelReliability: normalizePublicEvidenceRecords(value.topLabelReliability),
    classwiseReliability: normalizeEvidenceRowsMap(value.classwiseReliability),
    probabilityHistograms: normalizeEvidenceRowsMap(value.probabilityHistograms),
  };
}

function normalizePaFold(value: unknown): SportsPaFold | undefined {
  if (!isRecord(value)) return undefined;
  const foldId = publicString(value.foldId);
  if (!foldId) return undefined;
  return {
    foldId,
    status: publicString(value.status, "UNKNOWN"),
    validationSeason: optionalFiniteNumber(value.validationSeason),
    trainSeasons: numberArray(value.trainSeasons ?? value.trainingSeasons),
    trainingRows: optionalFiniteNumber(value.trainingRows),
    validationRows: optionalFiniteNumber(value.validationRows),
    rowCount: optionalFiniteNumber(value.rowCount ?? value.validationRows),
    metrics: normalizePaMetrics(value.metrics),
    rawMetrics: normalizePaMetrics(value.rawMetrics),
    calibratedMetrics: normalizePaMetrics(value.calibratedMetrics),
    predictionArtifact: optionalPublicEvidenceRecord(value.predictionArtifact),
  };
}

function normalizePaCandidate(value: unknown): SportsPaCandidate | undefined {
  if (!isRecord(value)) return undefined;
  const candidateId = publicString(value.candidateId ?? value.id);
  if (!candidateId) return undefined;
  const foldValues = Array.isArray(value.folds)
    ? value.folds
    : Array.isArray(value.foldMetrics) ? value.foldMetrics : [];
  const aggregateEvidence = normalizePublicEvidenceRecord(value.aggregateMetrics);
  const aggregateMetricSource = isRecord(value.aggregateMetrics) && isRecord(value.aggregateMetrics.selection2024)
    ? value.aggregateMetrics.selection2024
    : value.aggregateMetrics;
  return {
    candidateId,
    name: publicString(value.name ?? value.displayName, candidateId),
    definition: publicString(value.definition ?? value.candidateType),
    candidateType: publicString(value.candidateType ?? value.definition),
    ordinal: optionalFiniteNumber(value.ordinal),
    status: publicString(value.status, value.eligible === false ? "REJECTED" : value.eligible === true ? "ELIGIBLE" : "UNKNOWN"),
    selected: value.selected === true,
    eligible: typeof value.eligible === "boolean" ? value.eligible : undefined,
    rejectionReasons: publicStringArray(value.rejectionReasons),
    hyperparameters: normalizePublicEvidenceRecord(value.hyperparameters ?? value.config),
    aggregateMetrics: normalizePaMetrics(aggregateMetricSource),
    aggregateEvidence,
    convergence: value.convergence === undefined ? undefined : sanitizePublicEvidenceValue(value.convergence),
    runtimeSeconds: optionalFiniteNumber(value.runtimeSeconds),
    folds: foldValues.flatMap((item) => {
      const fold = normalizePaFold(item);
      return fold ? [fold] : [];
    }),
  };
}

function normalizePaFeatureView(value: unknown): SportsPaFeatureView | undefined {
  if (!isRecord(value)) return undefined;
  const featureViewId = publicString(value.featureViewId);
  if (!featureViewId) return undefined;
  const logicalRoot = publicString(value.logicalRoot ?? value.logicalUri);
  const artifactSha = publicString(value.artifactSha);
  return {
    featureViewId,
    contractVersion: publicString(value.contractVersion),
    contractSha: publicString(value.contractSha),
    contentSha: publicString(value.contentSha),
    logicalRoot,
    artifactSha,
    artifactBytes: optionalFiniteNumber(value.artifactBytes),
    rowCount: optionalFiniteNumber(value.rowCount),
    classOrder: publicStringArray(value.classOrder),
    seasonRows: normalizePublicEvidenceRecords(value.seasonRows ?? value.seasons),
    features: normalizePublicEvidenceItems(value.features ?? value.featureNames),
    artifacts: [],
  };
}

function normalizePaExperiment(value: unknown): SportsPaExperiment | undefined {
  if (!isRecord(value)) return undefined;
  const experimentId = publicString(value.experimentId);
  if (!experimentId) return undefined;
  return {
    experimentId,
    status: publicString(value.status, "RECORDED"),
    objective: publicString(value.objective),
    seed: optionalFiniteNumber(value.seed),
    trainingContractVersion: publicString(value.trainingContractVersion),
    startedAt: publicString(value.startedAt),
    completedAt: publicString(value.completedAt),
    durationSeconds: optionalFiniteNumber(value.durationSeconds ?? value.runtimeSeconds),
    tuningPolicy: value.tuningPolicy === undefined
      ? value.seed !== undefined || value.trainingContractVersion !== undefined
        ? sanitizePublicEvidenceValue({ seed: value.seed, trainingContractVersion: value.trainingContractVersion })
        : undefined
      : sanitizePublicEvidenceValue(value.tuningPolicy),
  };
}

function normalizePaCalibration(value: unknown): SportsPaCalibration | undefined {
  if (!isRecord(value)) return undefined;
  return {
    status: publicString(value.status ?? value.decision, "RECORDED"),
    sourceSeason: optionalFiniteNumber(value.sourceSeason),
    retained: typeof value.retained === "boolean" ? value.retained : undefined,
    fittedTemperature: optionalFiniteNumber(value.fittedTemperature),
    retainedTemperature: optionalFiniteNumber(value.retainedTemperature),
    reason: publicString(value.reason ?? value.rationale),
    raw2024: normalizePaMetrics(value.raw2024 ?? value.rawMetrics2024),
    scaled2024: normalizePaMetrics(value.scaled2024 ?? value.scaledMetrics2024 ?? value.calibrated2024),
    raw2025: normalizePaMetrics(value.raw2025 ?? value.rawMetrics2025),
    scaled2025: normalizePaMetrics(value.scaled2025 ?? value.scaledMetrics2025 ?? value.calibrated2025),
    final2025: normalizePaMetrics(value.final2025 ?? value.finalMetrics2025),
  };
}

function normalizePaBootstrapComparison(value: unknown): SportsPaBootstrapComparison | undefined {
  if (!isRecord(value)) return undefined;
  const evidence = isRecord(value.evidence) ? value.evidence : {};
  const comparatorCandidateId = publicString(value.comparatorCandidateId ?? value.baselineCandidateId);
  if (!comparatorCandidateId) return undefined;
  return {
    comparatorCandidateId,
    comparatorName: publicString(value.comparatorName, comparatorCandidateId),
    foldId: publicString(value.foldId),
    validationSeason: optionalFiniteNumber(value.validationSeason),
    resampleCount: optionalFiniteNumber(value.resampleCount ?? value.resamples ?? evidence.resampleCount),
    seed: optionalFiniteNumber(value.seed),
    logLossDifference: normalizePublicEvidenceRecord(value.logLossDifference ?? evidence.logLossDifference),
    brierScoreDifference: normalizePublicEvidenceRecord(value.brierScoreDifference ?? evidence.brierScoreDifference),
  };
}

function normalizePaRegistry(value: unknown): SportsPaRegistry | undefined {
  if (!isRecord(value)) return undefined;
  const artifacts = normalizePublicEvidenceRecords(value.artifacts);
  const modelId = publicString(value.modelId);
  if (!modelId && !artifacts.length) return undefined;
  const artifactId = publicString(value.artifactId);
  const logicalUri = publicString(value.logicalUri);
  return {
    modelId,
    artifactId,
    status: publicString(value.status, value.active === true ? "RECORDED" : "UNKNOWN"),
    logicalUri,
    registeredAt: publicString(value.registeredAt),
    lastValidatedAt: publicString(value.lastValidatedAt),
    active: typeof value.active === "boolean" ? value.active : undefined,
    artifacts,
  };
}

function normalizePaGraph(value: unknown): SportsPaGraph | undefined {
  if (!isRecord(value)) return undefined;
  const nodes = normalizePublicEvidenceRecords(value.nodes);
  return {
    graphId: publicString(value.graphId) || undefined,
    parentGraphId: publicString(value.parentGraphId) || undefined,
    status: publicString(value.status, nodes.length ? "RECORDED" : "NOT_CONFIGURED"),
    nodes,
    edges: normalizePublicEvidenceRecords(value.edges),
  };
}

function normalizePaBaseline(value: unknown): SportsPaBaseline | undefined {
  if (!isRecord(value)) return undefined;
  const run = isRecord(value.run) ? value.run : value;
  const runId = publicString(value.runId ?? run.runId);
  if (!runId) return undefined;
  const selected = optionalPublicEvidenceRecord(value.selected);
  const decisionRecord = isRecord(value.decision) ? value.decision : undefined;
  const decision = publicString(decisionRecord?.status ?? decisionRecord?.decision ?? decisionRecord?.terminalStatus ?? value.decision ?? run.terminalStatus);
  const selectedCandidateId = publicString(value.selectedCandidateId ?? selected?.candidateId ?? selected?.id);
  const candidates = Array.isArray(value.candidates) ? value.candidates.flatMap((item) => {
    const candidate = normalizePaCandidate(item);
    return candidate ? [{ ...candidate, selected: candidate.selected || candidate.candidateId === selectedCandidateId }] : [];
  }) : [];
  const selectedCandidate = candidates.find((candidate) => candidate.candidateId === selectedCandidateId || candidate.selected);
  const classOrder = publicStringArray(value.classOrder ?? run.classOrder);
  const normalizedFeatureView = normalizePaFeatureView(value.featureView);
  const registry = normalizePaRegistry(value.registry);
  const featureViewArtifact = normalizedFeatureView && registry?.artifacts.find((artifact) => (
    publicString(artifact.artifactType) === "FEATURE_VIEW"
    && publicString(artifact.logicalUri) === normalizedFeatureView.logicalRoot
    && publicString(artifact.sha256) === normalizedFeatureView.artifactSha
    && optionalFiniteNumber(artifact.byteCount) === normalizedFeatureView.artifactBytes
  ));
  const featureView = normalizedFeatureView
    ? {
        ...normalizedFeatureView,
        classOrder: normalizedFeatureView.classOrder.length ? normalizedFeatureView.classOrder : classOrder,
        artifacts: featureViewArtifact ? [featureViewArtifact] : [],
      }
    : undefined;
  const topLevelArtifacts = normalizePublicEvidenceRecords(value.artifacts);
  const bootstrapValues = Array.isArray(value.bootstrapComparisons)
    ? value.bootstrapComparisons
    : Array.isArray(value.bootstrap) ? value.bootstrap : [];
  return {
    schemaVersion: publicString(value.schemaVersion ?? run.schemaVersion),
    runId,
    runSha: publicString(value.runSha ?? run.runSha),
    projectId: publicString(value.projectId ?? run.projectId),
    status: publicString(value.status ?? run.terminalStatus, decision || "UNKNOWN"),
    decision,
    decisionReason: publicString(value.decisionReason ?? decisionRecord?.reason ?? decisionRecord?.rationale),
    parent: optionalPublicEvidenceRecord(value.parent ?? run.parent),
    identityBridge: optionalPublicEvidenceRecord(value.identityBridge ?? run.identityBridge),
    classOrder,
    featureView,
    experiment: normalizePaExperiment(value.experiment ?? run.experiment),
    candidates,
    selectedCandidateId,
    selected,
    selectedHyperparameters: normalizePublicEvidenceRecord(value.selectedHyperparameters ?? selected?.hyperparameters ?? selected?.config ?? selectedCandidate?.hyperparameters),
    calibration: normalizePaCalibration(value.calibration),
    bootstrapComparisons: bootstrapValues.flatMap((item) => {
      const comparison = normalizePaBootstrapComparison(item);
      return comparison ? [comparison] : [];
    }),
    registry,
    artifacts: topLevelArtifacts.length ? topLevelArtifacts : registry?.artifacts ?? [],
    graph: normalizePaGraph(value.graph),
    limitations: publicStringArray(value.limitations ?? decisionRecord?.limitations),
  };
}

function normalizePhase4Artifact(value: unknown): SportsPhase4Artifact | undefined {
  if (!isRecord(value)) return undefined;
  const artifactId = publicString(value.artifactId);
  const componentId = publicString(value.componentId);
  const logicalUri = publicString(value.logicalUri);
  const sha256 = publicString(value.sha256 ?? value.artifactSha);
  if (!artifactId || !logicalUri || !sha256) return undefined;
  return {
    artifactId,
    componentId,
    artifactType: publicString(value.artifactType, "RESEARCH_EVIDENCE"),
    logicalUri,
    sha256,
    byteCount: optionalFiniteNumber(value.byteCount ?? value.artifactBytes),
    mediaType: publicString(value.mediaType, "application/octet-stream"),
  };
}

function normalizePhase4Component(
  value: unknown,
  expectedType: SportsPhase4ComponentType,
  artifacts: SportsPhase4Artifact[],
): SportsPhase4Component | undefined {
  if (!isRecord(value)) return undefined;
  const componentId = publicString(value.componentId);
  const componentType = publicString(value.componentType).toUpperCase();
  const contractName = publicString(value.contractName);
  if (!componentId || componentType !== expectedType || !contractName) return undefined;
  const decision = isRecord(value.decision) ? value.decision : {};
  const status = publicString(
    decision.terminalStatus ?? decision.decision ?? decision.status ?? value.status,
    "BLOCKED",
  );
  const artifactIds = publicStringArray(value.artifactIds);
  const artifactSet = new Set(artifactIds);
  const candidates = normalizePublicEvidenceRecords(value.candidates);
  const candidateFolds = candidates.flatMap((candidate) => {
    const id = publicString(candidate.candidateId ?? candidate.id);
    const rows = Array.isArray(candidate.foldMetrics) ? candidate.foldMetrics : [];
    return rows.flatMap((item) => {
      if (!isRecord(item)) return [];
      const fold = normalizePublicEvidenceRecord(item);
      const season = optionalFiniteNumber(fold.validationSeason);
      return [{
        ...fold,
        candidateId: id,
        foldId: publicString(fold.foldId, season === 2024
          ? "train-2023-validate-2024"
          : season === 2025 ? "train-through-2024-validate-2025" : ""),
        trainingSeasons: Array.isArray(fold.trainingSeasons)
          ? fold.trainingSeasons
          : season === 2024 ? [2023] : season === 2025 ? [2023, 2024] : [],
      }];
    });
  });
  return {
    componentId,
    componentType: expectedType,
    contractName,
    contractSha: publicString(value.contractSha),
    status,
    decisionReason: publicString(decision.rationale ?? decision.reason ?? value.decisionReason),
    descriptor: normalizePublicEvidenceRecord(value.descriptor),
    candidates,
    selected: optionalPublicEvidenceRecord(value.selected),
    folds: candidateFolds.length ? candidateFolds : normalizePublicEvidenceRecords(value.folds),
    metrics: normalizePublicEvidenceRecord(value.metrics),
    calibration: optionalPublicEvidenceRecord(value.calibration),
    bootstrap: normalizePublicEvidenceRecords(value.bootstrap),
    coverage: normalizePublicEvidenceRecord(value.coverage),
    limitations: publicStringArray(value.limitations ?? decision.limitations),
    artifactIds,
    artifacts: artifacts.filter((artifact) => artifactSet.has(artifact.artifactId))
      .map((artifact) => ({ ...artifact, componentId })),
  };
}

function normalizePhase4Study(value: unknown): SportsPhase4Study | undefined {
  if (!isRecord(value)) return undefined;
  const studyId = publicString(value.studyId);
  if (!studyId) return undefined;
  const studyIdentity = isRecord(value.studyIdentity) ? value.studyIdentity : {};
  const componentValues = isRecord(value.components) ? value.components : {};
  const artifacts = Array.isArray(value.artifacts)
    ? value.artifacts.flatMap((item) => {
        const artifact = normalizePhase4Artifact(item);
        return artifact ? [artifact] : [];
      })
    : [];
  const components: SportsPhase4Study["components"] = {};
  const definitions: Array<[keyof SportsPhase4Study["components"], SportsPhase4ComponentType]> = [
    ["dynamicState", "DYNAMIC_PLAYER_STATE"],
    ["lineup", "LINEUP_PROJECTION"],
    ["starterDuration", "STARTER_DURATION"],
    ["bullpenUsage", "BULLPEN_USAGE"],
  ];
  for (const [key, componentType] of definitions) {
    const component = normalizePhase4Component(componentValues[key], componentType, artifacts);
    if (component) components[key] = component;
  }
  const decision = normalizePublicEvidenceRecord(value.decision);
  const registry = isRecord(value.registry) ? value.registry : {};
  return {
    schemaVersion: publicString(value.schemaVersion),
    studyId,
    studySha: publicString(value.studySha),
    projectId: publicString(value.projectId),
    createdAt: publicString(studyIdentity.createdAt ?? value.createdAt),
    codeRevision: publicString(studyIdentity.codeRevision ?? value.codeRevision),
    dataset: normalizePublicEvidenceRecord(value.dataset),
    identityBridge: normalizePublicEvidenceRecord(value.identityBridge),
    phase3Baseline: normalizePublicEvidenceRecord(value.phase3Baseline),
    components,
    artifacts,
    graph: normalizePaGraph(value.graph),
    decision,
    limitations: publicStringArray(value.limitations ?? decision.limitations),
    registeredAt: publicString(registry.registeredAt ?? value.registeredAt),
    lastValidatedAt: publicString(registry.lastValidatedAt ?? value.lastValidatedAt),
    active: typeof registry.active === "boolean"
      ? registry.active
      : typeof value.active === "boolean" ? value.active : undefined,
    catcherReadiness: normalizeCatcherReadiness(value.catcherReadiness),
    pitchSequenceFeatures: normalizePitchSequenceFeatures(value.pitchSequenceFeatures),
    processInteractions: normalizeProcessInteractions(value.processInteractions),
    incrementalSignalStudy: normalizeIncrementalSignalStudy(value.incrementalSignalStudy),
    severeMissForensics: normalizeSevereMissForensics(value.severeMissForensics),
    gameReplay: normalizeGameReplay(value.gameReplay),
    baseOutTransition: normalizeBaseOutTransition(value.baseOutTransition),
    simulationInput: normalizeSimulationInput(value.simulationInput),
    wholeGameMonteCarlo: normalizeWholeGameMonteCarlo(value.wholeGameMonteCarlo),
    participationAblation: normalizeParticipationAblation(value.participationAblation),
  };
}

function normalizeParticipationAblation(value: unknown): SportsParticipationAblation | undefined {
  if (!isRecord(value)) return undefined;
  const runId = publicString(value.runId);
  // Existence-gated: no governed ablation run -> honest not-run state.
  if (!runId) return undefined;
  return {
    runId,
    contractName: publicString(value.contractName),
    researchOnly: value.researchOnly !== false,
    branchLabels: normalizePublicEvidenceRecord(value.branchLabels),
    projectionAuthorities: normalizePublicEvidenceRecord(value.projectionAuthorities),
    simulationsPerGame: optionalFiniteNumber(value.simulationsPerGame),
    comparableGames: normalizePublicEvidenceRecord(value.comparableGames),
    bySeason: normalizePublicEvidenceRecord(value.bySeason),
    bootstrap: normalizePublicEvidenceRecord(value.bootstrap),
    stateFallback: normalizePublicEvidenceRecord(value.stateFallback),
    meanLineupRecall: normalizePublicEvidenceRecord(value.meanLineupRecall),
    overallDecision: publicString(value.overallDecision),
    lineupGameImpact: publicString(value.lineupGameImpact),
    starterDurationGameImpact: publicString(value.starterDurationGameImpact),
    bullpenGameImpact: publicString(value.bullpenGameImpact),
    remainingOracleDependencies: normalizePublicEvidenceRecord(value.remainingOracleDependencies),
    limitations: publicStringArray(value.limitations),
  };
}

function normalizeWholeGameMonteCarlo(value: unknown): SportsWholeGameMonteCarlo | undefined {
  if (!isRecord(value)) return undefined;
  const runId = publicString(value.runId);
  // Existence-gated: no governed Monte Carlo run -> honest not-run state.
  if (!runId) return undefined;
  return {
    runId,
    contractName: publicString(value.contractName),
    researchOnly: value.researchOnly !== false,
    participantMode: publicString(value.participantMode),
    parentAuthorities: normalizePublicEvidenceRecord(value.parentAuthorities),
    simulationsPerGame: optionalFiniteNumber(value.simulationsPerGame),
    developmentStandardSimulations: optionalFiniteNumber(value.developmentStandardSimulations),
    eligibleGames: normalizePublicEvidenceRecord(value.eligibleGames),
    convergence: normalizePublicEvidenceRecord(value.convergence),
    bySeason: normalizePublicEvidenceRecord(value.bySeason),
    d3GameLevelValue: publicString(value.d3GameLevelValue),
    contactQualityPriority: publicString(value.contactQualityPriority),
    participationAblationDecision: publicString(value.participationAblationDecision),
    simulatorReadiness: publicString(value.simulatorReadiness),
    legality: normalizePublicEvidenceRecord(value.legality),
    limitations: publicStringArray(value.limitations),
  };
}

function normalizeSimulationInput(value: unknown): SportsSimulationInput | undefined {
  if (!isRecord(value)) return undefined;
  const runId = publicString(value.runId);
  // Existence-gated: no governed simulation-input run -> honest not-run state.
  if (!runId) return undefined;
  return {
    runId,
    contractName: publicString(value.contractName),
    researchOnly: value.researchOnly !== false,
    parentAuthorities: normalizePublicEvidenceRecord(value.parentAuthorities),
    readiness: normalizePublicEvidenceRecord(value.readiness),
    monteCarloEntryDecision: publicString(value.monteCarloEntryDecision),
    monteCarloEntryGates: normalizePublicEvidenceRecord(value.monteCarloEntryGates),
    paProvider: normalizePublicEvidenceRecord(value.paProvider),
    participantProvider: normalizePublicEvidenceRecord(value.participantProvider),
    gameInitialization: normalizePublicEvidenceRecord(value.gameInitialization),
    shortSequenceIntegration: normalizePublicEvidenceRecord(value.shortSequenceIntegration),
    eligiblePopulation: normalizePublicEvidenceRecord(value.eligiblePopulation),
    monteCarloPerformanceEstimate: normalizePublicEvidenceRecord(value.monteCarloPerformanceEstimate),
    limitations: publicStringArray(value.limitations),
  };
}

function normalizeBaseOutTransition(value: unknown): SportsBaseOutTransition | undefined {
  if (!isRecord(value)) return undefined;
  const transitionRunId = publicString(value.transitionRunId);
  if (!transitionRunId) return undefined;
  return {
    transitionRunId,
    contractName: publicString(value.contractName),
    readinessStatus: publicString(value.readinessStatus),
    researchOnly: value.researchOnly !== false,
    parentReplayAuthority: normalizePublicEvidenceRecord(value.parentReplayAuthority),
    retainedPolicy: publicString(value.retainedPolicy),
    devSeasons: numberArray(value.devSeasons),
    developmentRows: optionalFiniteNumber(value.developmentRows),
    primaryStateCells: optionalFiniteNumber(value.primaryStateCells),
    sparseCellCount: optionalFiniteNumber(value.sparseCellCount),
    deterministicRules: publicStringArray(value.deterministicRules),
    illegalProbabilityMass: optionalFiniteNumber(value.illegalProbabilityMass),
    validation2024: normalizePublicEvidenceRecord(value.validation2024),
    frozen2025: normalizePublicEvidenceRecord(value.frozen2025),
    stochasticStressTest: normalizePublicEvidenceRecord(value.stochasticStressTest),
    reproducibility: normalizePublicEvidenceRecord(value.reproducibility),
    modelArtifact: normalizePublicEvidenceRecord(value.modelArtifact),
    limitations: publicStringArray(value.limitations),
  };
}

function normalizeGameReplay(value: unknown): SportsGameReplay | undefined {
  if (!isRecord(value)) return undefined;
  const replayRunId = publicString(value.replayRunId);
  // Existence-gated: no governed replay run -> honest not-run state.
  if (!replayRunId) return undefined;
  return {
    replayRunId,
    contractName: publicString(value.contractName),
    researchOnly: value.researchOnly !== false,
    probabilisticSimulation: value.probabilisticSimulation === true,
    readinessStatus: publicString(value.readinessStatus),
    seasons: numberArray(value.seasons),
    sourceFamily: publicString(value.sourceFamily),
    fullExecuted: value.fullExecuted === true,
    gamesAttempted: optionalFiniteNumber(value.gamesAttempted),
    classificationCounts: normalizePublicEvidenceRecord(value.classificationCounts),
    exactReplayRate: optionalFiniteNumber(value.exactReplayRate),
    finalScoreExactRate: optionalFiniteNumber(value.finalScoreExactRate),
    inningSequenceExactRate: optionalFiniteNumber(value.inningSequenceExactRate),
    zeroContinuityRate: optionalFiniteNumber(value.zeroContinuityRate),
    mismatchesByCategory: normalizePublicEvidenceRecord(value.mismatchesByCategory),
    mismatchForensics: normalizePublicEvidenceRecords(value.mismatchForensics),
    limitations: publicStringArray(value.limitations),
  };
}

function normalizeSevereMissForensics(value: unknown): SportsSevereMissForensics | undefined {
  if (!isRecord(value)) return undefined;
  const studyId = publicString(value.studyId);
  // Existence-gated: no governed study id -> honest not-run state.
  if (!studyId) return undefined;
  return {
    studyId,
    contractName: publicString(value.contractName),
    researchOnly: value.researchOnly !== false,
    officialPopulationPreserved: value.officialPopulationPreserved !== false,
    population: normalizePublicEvidenceRecord(value.population),
    anchor: normalizePublicEvidenceRecord(value.anchor),
    pareto2025: normalizePublicEvidenceRecords(value.pareto2025),
    tailSensitivity2025: normalizePublicEvidenceRecord(value.tailSensitivity2025),
    overIndex2025: normalizePublicEvidenceRecord(value.overIndex2025),
    confusionPairs2025: normalizePublicEvidenceRecords(value.confusionPairs2025),
    severeMissClassifier: normalizePublicEvidenceRecord(value.severeMissClassifier),
    randomness: normalizePublicEvidenceRecord(value.randomness),
    topThreePatterns: normalizePublicEvidenceRecords(value.topThreePatterns),
    recommendedNextStep: publicString(value.recommendedNextStep),
    limitations: publicStringArray(value.limitations),
  };
}

function normalizeIncrementalSignalStudy(value: unknown): SportsIncrementalSignalStudy | undefined {
  if (!isRecord(value)) return undefined;
  const studyId = publicString(value.studyId);
  // Existence-gated: no governed study id -> honest not-run state.
  if (!studyId) return undefined;
  return {
    studyId,
    contractName: publicString(value.contractName),
    researchOnly: value.researchOnly !== false,
    promotedModel: value.promotedModel === true,
    changesChampionStatus: value.changesChampionStatus === true,
    modelPolicy: normalizePublicEvidenceRecord(value.modelPolicy),
    population: normalizePublicEvidenceRecord(value.population),
    branchFeatureCounts: normalizePublicEvidenceRecord(value.branchFeatureCounts),
    anchor: normalizePublicEvidenceRecord(value.anchor),
    incrementalRows: normalizePublicEvidenceRecords(value.incrementalRows),
    practicalBandDefinition: normalizePublicEvidenceRecord(value.practicalBandDefinition),
    strikeout: normalizePublicEvidenceRecord(value.strikeout),
    walkHbpCi: normalizePublicEvidenceRecord(value.walkHbpCi),
    bootstrap: normalizePublicEvidenceRecords(value.bootstrap),
    decision: normalizePublicEvidenceRecord(value.decision),
    nextStep: normalizePublicEvidenceRecord(value.nextStep),
    limitations: publicStringArray(value.limitations),
  };
}

function normalizeProcessInteractions(value: unknown): SportsProcessInteractions | undefined {
  if (!isRecord(value)) return undefined;
  const terminalStatus = publicString(value.terminalStatus);
  if (!terminalStatus) return undefined;
  return {
    terminalStatus,
    seasons: numberArray(value.seasons),
    featureCount: optionalFiniteNumber(value.featureCount),
    featureHardMax: optionalFiniteNumber(value.featureHardMax),
    materializationId: publicString(value.materializationId),
    parentE1: normalizePublicEvidenceRecord(value.parentE1),
    interactionFamilies: normalizePublicEvidenceRecord(value.interactionFamilies),
    features: publicStringArray(value.features),
    coverage: normalizePublicEvidenceRecord(value.coverage),
    redundancy: normalizePublicEvidenceRecord(value.redundancy),
    strikeoutWalkReadiness: normalizePublicEvidenceRecord(value.strikeoutWalkReadiness),
    rowsRead: optionalFiniteNumber(value.rowsRead),
    rowsMaterialized: optionalFiniteNumber(value.rowsMaterialized),
    limitations: publicStringArray(value.limitations),
  };
}

function normalizePitchSequenceFeatures(value: unknown): SportsPitchSequenceFeatures | undefined {
  if (!isRecord(value)) return undefined;
  const terminalStatus = publicString(value.terminalStatus);
  // Existence-gated: no governed terminal status -> honest not-run state.
  if (!terminalStatus) return undefined;
  return {
    terminalStatus,
    parserVersion: publicString(value.parserVersion),
    seasons: numberArray(value.seasons),
    trailingWindowDays: optionalFiniteNumber(value.trailingWindowDays),
    batterFeatureCount: optionalFiniteNumber(value.batterFeatureCount),
    pitcherFeatureCount: optionalFiniteNumber(value.pitcherFeatureCount),
    totalFeatureCount: optionalFiniteNumber(value.totalFeatureCount),
    rowsRead: optionalFiniteNumber(value.rowsRead),
    rowsMaterialized: optionalFiniteNumber(value.rowsMaterialized),
    materializationId: publicString(value.materializationId),
    parseQuality: normalizePublicEvidenceRecord(value.parseQuality),
    parserCategories: normalizePublicEvidenceRecords(value.parserCategories),
    coverage: normalizePublicEvidenceRecord(value.coverage),
    earlySeasonMissing: normalizePublicEvidenceRecord(value.earlySeasonMissing),
    featureSummary: normalizePublicEvidenceRecords(value.featureSummary),
    strikeoutWalkReadiness: normalizePublicEvidenceRecord(value.strikeoutWalkReadiness),
    rareOutcomeLimitations: publicStringArray(value.rareOutcomeLimitations),
    limitations: publicStringArray(value.limitations),
  };
}

function normalizeCatcherReadiness(value: unknown): SportsCatcherReadiness | undefined {
  if (!isRecord(value)) return undefined;
  const decision = isRecord(value.decision) ? value.decision : {};
  const terminalStatus = publicString(value.terminalStatus ?? decision.status);
  // Existence-gated: without a governed terminal status this is an honest NOT_RUN
  // state, never a fabricated audit result.
  if (!terminalStatus) return undefined;
  return {
    contractName: publicString(value.contractName, "MLB_CATCHER_INFLUENCE_READINESS_V1"),
    terminalStatus,
    rationale: publicString(decision.rationale ?? value.rationale),
    seasons: numberArray(value.seasons),
    startingCatcherCoverage: normalizePublicEvidenceRecord(value.startingCatcherCoverage),
    paCatcherAssignmentCoverage: normalizePublicEvidenceRecord(value.paCatcherAssignmentCoverage),
    batterySampleDistribution: normalizePublicEvidenceRecord(value.batterySampleDistribution),
    batteryFallbackLevels: normalizePublicEvidenceRecord(value.batteryFallbackLevels),
    catcherBatterSampleDistribution: normalizePublicEvidenceRecord(value.catcherBatterSampleDistribution),
    freeFeatureInventory: normalizePublicEvidenceRecords(value.freeFeatureInventory),
    premiumDataGaps: normalizePublicEvidenceRecords(value.premiumDataGaps),
    limitations: publicStringArray(value.limitations),
  };
}

function normalizeFeatureAudit(value: unknown): SportsFeatureAudit | undefined {
  if (!isRecord(value) || typeof value.contractVersion !== "string" || typeof value.status !== "string") return undefined;
  const namespaces = isRecord(value.observedNamespaces) ? value.observedNamespaces : {};
  const joinEvidence = isRecord(value.joinEvidence) ? value.joinEvidence : {};
  const missingBridge = isRecord(value.missingBridge) ? value.missingBridge : {};
  const perSeasonRows = Array.isArray(value.perSeasonRows) ? value.perSeasonRows.flatMap((item) => {
    if (!isRecord(item)) return [];
    return [{
      season: finiteNumber(item.season),
      plateAppearanceRows: finiteNumber(item.plateAppearanceRows),
      eligibleBattingPriorRows: finiteNumber(item.eligibleBattingPriorRows),
      eligiblePitchingPriorRows: finiteNumber(item.eligiblePitchingPriorRows),
      batterYMinus1JoinMatches: finiteNumber(item.batterYMinus1JoinMatches),
      batterYMinus1JoinDenominator: finiteNumber(item.batterYMinus1JoinDenominator),
      pitcherYMinus1JoinMatches: finiteNumber(item.pitcherYMinus1JoinMatches),
      pitcherYMinus1JoinDenominator: finiteNumber(item.pitcherYMinus1JoinDenominator),
    }];
  }) : [];
  return {
    contractVersion: value.contractVersion,
    status: value.status,
    method: typeof value.method === "string" ? value.method : "PACKAGE_ONLY_AUDIT",
    observedNamespaces: {
      plateAppearance: stringArray(namespaces.plateAppearance),
      playerPrior: stringArray(namespaces.playerPrior),
    },
    perSeasonRows,
    joinEvidence: {
      batterMatches: finiteNumber(joinEvidence.batterMatches),
      batterDenominator: finiteNumber(joinEvidence.batterDenominator),
      pitcherMatches: finiteNumber(joinEvidence.pitcherMatches),
      pitcherDenominator: finiteNumber(joinEvidence.pitcherDenominator),
      inferenceOrFuzzyMatchingUsed: joinEvidence.inferenceOrFuzzyMatchingUsed === true,
      sameSeasonPredictorEligibleObserved: joinEvidence.sameSeasonPredictorEligibleObserved === true,
      plateAppearanceCanonicalIdentityResolvedObserved: joinEvidence.plateAppearanceCanonicalIdentityResolvedObserved === true,
    },
    missingBridge: {
      isMissing: missingBridge.isMissing === true,
      requiredArtifact: typeof missingBridge.requiredArtifact === "string" ? missingBridge.requiredArtifact : "Governed identity bridge",
      reason: typeof missingBridge.reason === "string" ? missingBridge.reason : "The required governed identity bridge is not registered.",
    },
    auditedAt: typeof value.auditedAt === "string" ? value.auditedAt : undefined,
  };
}

function normalizeProject(value: unknown): RegisteredSportsProject | undefined {
  if (!isRecord(value) || typeof value.projectId !== "string") return undefined;
  const workflowEvidence = isRecord(value.workflowEvidence) ? value.workflowEvidence : {};
  const stages = Array.isArray(value.stages)
    ? value.stages as SportsProjectStage[]
    : Object.entries(workflowEvidence).flatMap(([key, item]) => {
        const definition = MLB_PROJECT_STAGE_MAP[key];
        if (!definition || !isRecord(item)) return [];
        return [{
          ...definition,
          status: String(item.status || "NOT_CONFIGURED"),
          evidence: typeof item.evidence === "string" ? [item.evidence] : stringArray(item.evidence),
        }];
      });
  return {
    projectId: value.projectId,
    name: String(value.name || value.projectName || "Governed MLB Project"),
    status: typeof value.status === "string" ? value.status : "REGISTERED",
    sport: typeof value.sport === "string" ? value.sport : undefined,
    league: typeof value.league === "string" ? value.league : undefined,
    developmentPeriod: typeof value.developmentPeriod === "string" ? value.developmentPeriod : undefined,
    priorHistory: typeof value.priorHistory === "string" ? value.priorHistory : undefined,
    primaryTarget: typeof value.primaryTarget === "string" ? value.primaryTarget : undefined,
    secondaryTargets: stringArray(value.secondaryTargets),
    forecastLifecycle: typeof value.forecastLifecycle === "string" ? value.forecastLifecycle : undefined,
    baselinePopulation: typeof value.baselinePopulation === "string" ? value.baselinePopulation : undefined,
    upperBoundPopulation: typeof value.upperBoundPopulation === "string" ? value.upperBoundPopulation : undefined,
    researchPurpose: typeof value.researchPurpose === "string" ? value.researchPurpose : undefined,
    workflowId: typeof value.workflowId === "string" ? value.workflowId : "mlb-forecasting",
    stages,
    featureAudit: normalizeFeatureAudit(value.featureAudit),
  };
}

function normalizeActiveDataset(value: ActiveSportsDataset): ActiveSportsDataset {
  const raw = value as unknown as Record<string, unknown>;
  const coverage = isRecord(raw.evidenceCoverage)
    ? Object.entries(raw.evidenceCoverage).map(([evidence, item]) => {
        if (!isRecord(item)) return { evidence, status: String(item) };
        const details = Object.entries(item)
          .filter(([key]) => key !== "status" && key !== "bySeason")
          .map(([key, detail]) => `${key.replaceAll("_", " ")}: ${typeof detail === "number" ? detail.toLocaleString("en-US") : String(detail)}`);
        return { evidence, status: String(item.status || "RECORDED"), detail: details.join(" · ") || undefined };
      })
    : value.evidenceCoverage;
  const rights = Array.isArray(raw.rights) ? raw.rights.flatMap((item) => {
    if (!isRecord(item)) return [];
    return [{
      source: String(item.source || item.displayName || item.sourceName || "Source-right control"),
      status: typeof item.status === "string" ? item.status : undefined,
      attribution: typeof item.attribution === "string" ? item.attribution : undefined,
      allowedUses: stringArray(item.allowedUses),
      prohibitedUses: stringArray(item.prohibitedUses),
    }];
  }) : [];
  const limitations = Array.isArray(raw.limitations) ? raw.limitations.flatMap((item) => {
    if (typeof item === "string") return [item];
    return isRecord(item) && typeof item.description === "string" ? [item.description] : [];
  }) : [];
  const populations = Array.isArray(raw.populations) ? raw.populations.flatMap((item) => {
    if (!isRecord(item)) return [];
    return [{
      populationId: String(item.populationId || "population"),
      rows: Number(item.rows) || 0,
      predicate: typeof item.predicate === "string" ? item.predicate : JSON.stringify(item.predicate ?? {}),
      uses: stringArray(item.uses),
      prohibitions: stringArray(item.prohibitions),
    }];
  }) : [];
  return {
    ...value,
    evidenceCoverage: coverage,
    rights,
    limitations,
    populations,
    project: normalizeProject(raw.project),
    featureAudit: normalizeFeatureAudit(raw.featureAudit),
    identityBridge: normalizeIdentityBridge(raw.identityBridge),
    paBaseline: normalizePaBaseline(raw.paBaseline),
    phase4: normalizePhase4Study(raw.phase4),
  };
}

async function getEvidence<T>(path: string, key: string, signal: AbortSignal): Promise<T | null> {
  const response = await fetch(`${BASE}${path}`, {
    method: "GET",
    credentials: "include",
    signal,
    headers: {
      Accept: "application/json",
      ...(devUserId ? { "X-ATLAS-USER-ID": devUserId } : {}),
    },
  });
  if (response.status === 404 || response.status === 204) return null;
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(publicErrorMessage(payload, `HTTP ${response.status}`));
  }
  if (!isRecord(payload)) return null;
  const hasEnvelopeKey = Object.prototype.hasOwnProperty.call(payload, key);
  if (hasEnvelopeKey && !isRecord(payload[key])) return null;
  const unwrapped = hasEnvelopeKey ? payload[key] as Record<string, unknown> : payload;
  return Object.keys(unwrapped).length > 0 ? unwrapped as T : null;
}

export async function getActiveSportsDataset(signal: AbortSignal) {
  const dataset = await getEvidence<ActiveSportsDataset>("/sports/datasets/active", "dataset", signal);
  return dataset ? normalizeActiveDataset(dataset) : null;
}

export async function registerApprovedSportsDataset(): Promise<ActiveSportsDataset | null> {
  const response = await fetch(`${BASE}/sports/datasets/register-approved`, {
    method: "POST",
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...(devUserId ? { "X-ATLAS-USER-ID": devUserId } : {}),
    },
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(publicErrorMessage(payload, `Registration failed with HTTP ${response.status}`));
  }
  if (!isRecord(payload)) return null;
  return isRecord(payload.dataset) ? normalizeActiveDataset(payload.dataset as ActiveSportsDataset) : null;
}

function useEvidence<T>(loader: (signal: AbortSignal) => Promise<T | null>): RefreshableEvidenceState<T> {
  const [state, setState] = useState<EvidenceState<T>>(initialEvidenceState);
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision((current) => current + 1), []);
  useEffect(() => {
    const controller = new AbortController();
    setState(initialEvidenceState);
    void loader(controller.signal)
      .then((data) => setState(data
        ? { status: "ready", data, error: null }
        : { status: "empty", data: null, error: null }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          status: "error",
          data: null,
          error: error instanceof Error ? error.message : "Evidence service unavailable",
        });
      });
    return () => controller.abort();
  }, [loader, revision]);
  return { ...state, refresh } as RefreshableEvidenceState<T>;
}

export function useActiveSportsDataset() {
  return useEvidence(getActiveSportsDataset);
}

export function logicalExchangeUri(value: string | undefined) {
  return value?.startsWith("asp-model-exchange://") ? value : "Logical URI unavailable";
}

export function logicalSportsEvidenceUri(value: string | undefined) {
  return value?.startsWith("asp-model-exchange://") || value?.startsWith("asp-model-studio-runtime://")
    ? value
    : "Logical URI unavailable";
}
