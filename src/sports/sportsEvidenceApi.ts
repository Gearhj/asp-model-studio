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
