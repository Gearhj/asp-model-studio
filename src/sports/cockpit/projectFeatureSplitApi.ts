import { BASE, getJSON, postJSON } from "../../lib/api";
import {
  GOVERNED_PRIOR_BINDING_READY_STATUS,
  GOVERNED_PRIOR_BLOCKED_STATUS,
  GOVERNED_PRIOR_EXECUTABLE_STATUS,
  GOVERNED_PRIOR_RETIRED_STATUS,
} from "./projectTreatmentApi";

export type StudioAudit = {
  finalOotTargetAccessed: false;
  finalOotUsedForSelection: false;
  legacyGlobalMatrixUsed: false;
  providerCalls: 0;
  sourceOrGoldMutated?: false;
  modelActivity: {
    fits: number;
    scores: number;
    tunes: number;
    calibrations: number;
    selections: number;
    promotions: number;
  };
};

export type StudioAuthority = {
  projectId: string;
  sourceDatasetId: string;
  sourceManifestSha: string;
  goldDatasetId: string;
  goldManifestSha: string;
  contextualDatasetId: string;
  contextualManifestSha: string;
  reviewDigest: string;
  authorityKey: string;
};

export type StudioPopulation = {
  scope: "DEVELOPMENT_ONLY";
  developmentRows: number;
  finalOotRows: number;
  finalOotLocked: true;
  developmentEndDate: string;
};

export type StudioEnvelope<T> = {
  ok: true;
  authority: StudioAuthority;
  population: StudioPopulation;
  audit: StudioAudit;
  data: T;
};

export type FeatureStatus = "ACTIVE" | "INACTIVE" | "UNAVAILABLE";

export type GovernedPreprocessingPriorAuthority = {
  featureName?: string;
  authorityName: string;
  authorityId: string;
  method: string;
  hierarchy: string[];
  exposureFeature: string | null;
  exposureDefinition: string;
  reliability: string;
  foldLocal: string;
  pointInTime: string;
  status: string;
  executable: boolean;
  selectable: boolean;
  blockedReason: string | null;
  resolution: string | null;
  retirementReason: string | null;
  derivedOutputs: string[];
  readyFeatureCount: number | null;
  bindingReadyRequiresWave2EngineFeatureCount: number | null;
  retiredFeatureCount: number | null;
  blockedFeatureCount: number | null;
  featureCount: number | null;
  bindings: GovernedPreprocessingPriorAuthority[];
};

export type PriorExecutionSummary = Record<string, unknown> & {
  hierarchicalPriorReady?: number;
  hierarchicalPriorBindingReady?: number;
  hierarchicalPriorRetired?: number;
  hierarchicalPriorBlocked?: number;
};

export type GovernedInteractionParentTreatmentAuthority =
  | string
  | (Record<string, unknown> & {
      parentFeature?: string;
      backendFeatureIdentity?: string;
      status?: string;
    });

export type GovernedInteractionAuthority = {
  featureName: string;
  backendFeatureIdentity: string;
  formula: string;
  formulaVersion: string;
  orderedParents: string[];
  parentTreatmentAuthorities: GovernedInteractionParentTreatmentAuthority[];
  operationOrder: string[];
  pointInTime: string;
  foldLocal: string;
  status: string;
  blockedReason: string | null;
};

export type GovernedInteractionAuthoritySummary = {
  authorityName: string;
  authorityId: string;
  authorityChecksum: string;
  foldLocal: string;
  pointInTime: string;
  featureCount: number | null;
  readyFeatureCount: number | null;
  blockedFeatureCount: number | null;
  bindings: GovernedInteractionAuthority[];
};

export type TreatmentSpecificationResolution = {
  executableStatus: string;
  executable: boolean;
  executableSelectable: boolean;
  blockedReason: string | null;
  resolution: string | null;
  retirementReason: string | null;
  scientificRecommendation: string;
  priorAuthority: GovernedPreprocessingPriorAuthority | null;
  interactionAuthority: GovernedInteractionAuthority | null;
  derivedPriorOutputs: string[];
};

export type TreatmentSpecificationDraftAuthority = {
  specificationDraftId: string;
  specificationVersion: number | null;
  manifestChecksum: string;
  status: string;
  priorAuthority: GovernedPreprocessingPriorAuthority | null;
  interactionAuthority: GovernedInteractionAuthoritySummary | null;
  executionSummary: PriorExecutionSummary;
};

export type FeatureInventoryRow = {
  order: number;
  featureName: string;
  friendlyLabel: string;
  family: string;
  core: boolean;
  dataType: string;
  role: string;
  definition: string;
  sourceLineage: string;
  earliestAvailableDate: string | null;
  latestDevelopmentDate: string;
  developmentCoveragePercent: number | null;
  physicalMissingPercent: number | null;
  coldStartRelevant: boolean;
  outlierPrevalencePercent: number | null;
  missingValueTreatment: string;
  outlierTreatment: string;
  pointInTimeTreatment: string;
  forecastTimeAvailability: string;
  simulationGeneratedState: boolean;
  leakageRisk: string;
  cardinality: number | null;
  range: string;
  interactionMembership: string[];
  status: FeatureStatus;
  unavailableReason: string | null;
  selectedCandidateSets: string[];
  eligibleTransformations: string[];
  selectedTransformation: string;
  treatmentSpecificationResolution: TreatmentSpecificationResolution | null;
  targetClassComparison?: { label: string; value: number }[];
  temporalCoverage?: { label: string; value: number }[];
  missingnessBySeason?: { label: string; value: number }[];
  missingnessByMonth?: { label: string; value: number }[];
  redundancy?: { feature: string; value: number }[];
};

export type FeatureFamily = {
  familyId: string;
  friendlyName: string;
  orderedFeatures: string[];
  featureCount: number;
  eligibleFeatureCount: number;
  inactiveFeatureCount: number;
  unavailableFeatureCount: number;
  physicalMissingPercent: number | null;
  sourceUnavailableCount: number;
  coldStartExposurePercent: number | null;
  pointInTimeStatus: string;
  forecastTimeAvailability: string;
  interactionCount: number;
  modelCompatibility: string[];
  governanceWarnings: string[];
  excludedFeatures: { feature: string; reason: string }[];
  selected: boolean;
};

export type InteractionContract = {
  name: string;
  status: string;
  reason: string;
  parentVariables: string[];
  formula: string;
  formulaVersion: string;
  orderedParents: string[];
  parentTreatmentAuthorities: GovernedInteractionParentTreatmentAuthority[];
  operationOrder: string[];
  coveragePercent: number | null;
  missingPercent: number | null;
  pointInTimeStatus: string;
  foldLocal: string;
  executableStatus: string;
  blockedReason: string | null;
  selectedCandidateSets: string[];
};

export type FeatureSetVersion = {
  featureSetId: string;
  featureSetKey: string;
  version: number;
  status: "DRAFT" | "REGISTERED" | "SUPERSEDED" | "RETIRED" | "REGISTERED_SOURCE_DRAFT";
  name: string;
  description: string;
  orderedFeatures: string[];
  activeFeatureCount: number;
  unavailableExclusions: { feature: string; reason: string }[];
  transformationContracts: Record<string, string>;
  interactionContracts: Record<string, string>;
  outlierPolicyId: string;
  missingPolicyId: string;
  checksum: string;
  notes: string;
  createdAt: string;
};

export type FeatureStudioSummary = {
  summary: {
    coreFeatureCount: number;
    contextualFeatureCount: number;
    totalCandidateCount: number;
    eligibleContextualCount: number;
    inactiveFeatureCount: number;
    unavailableFeatureCount: number;
    familyCount: number;
    interactionCount: number;
    materializedInteractionCount: number;
    inactiveInteractionCount: number;
    unavailableInteractionCount: number;
    finalOotRows: number;
    finalOotLocked: boolean;
    selectedCandidateSetCount: number;
  };
  families: FeatureFamily[];
  interactions: InteractionContract[];
  recommendedSets: {
    setId: string;
    name: string;
    description: string;
    orderedFeatures: string[];
    activeFeatureCount: number;
    unavailableExclusions: { feature: string; reason: string }[];
    transformationContracts: Record<string, string>;
    interactionContracts: Record<string, string>;
  }[];
  treatmentPolicies: {
    outlier: { policyId: string; version: number; checksum: string };
    missing: { policyId: string; version: number; checksum: string };
  };
  visualizations: {
    familyCoverage: { family: string; coveragePercent: number }[];
    familyMissingness: { family: string; missingPercent: number }[];
    featureAvailabilityBySeason: { season: number; family: string; coveragePercent: number }[];
  };
  treatmentSpecificationDraft: TreatmentSpecificationDraftAuthority | null;
  priorAuthority: GovernedPreprocessingPriorAuthority | null;
  interactionAuthority: GovernedInteractionAuthoritySummary | null;
  featureSetState: FeatureSetState;
};

export type FeatureSetState = {
  expectedChecksum: string;
  draft: FeatureSetVersion | null;
  registered: FeatureSetVersion[];
  history: FeatureSetVersion[];
};

export const NO_CURRENT_SPLIT_CONTRACT = "NO_CURRENT_SPLIT_CONTRACT";

export type FeatureInventory = {
  rows: FeatureInventoryRow[];
  total: number;
  page: number;
  pageSize: number;
  filters: Record<string, unknown>;
};

export type SplitFold = {
  foldNumber: number;
  trainingStart: string;
  trainingEnd: string;
  validationStart: string;
  validationEnd: string;
  trainRows: number;
  validationRows: number;
  trainGames: number;
  validationGames: number;
  distinctValidationDates: number;
  batters: number;
  pitchers: number;
  coldStartPercent: number;
  physicalMissingPercent: number;
  trainingClassDistribution: { class: string; rows: number; percent: number }[];
  validationClassDistribution: { class: string; rows: number; percent: number }[];
  featureSetAvailability: { featureSetId: string; available: boolean; reason: string }[];
  preprocessingFitScope: string;
  checksum: string;
};

export type SplitQualityGate = {
  code: string;
  label: string;
  passed: boolean;
  blocking: boolean;
  detail: string;
};

export type SplitContractVersion = {
  splitContractId: string;
  version: number;
  status: "DRAFT" | "REGISTERED" | "SUPERSEDED" | "REGISTERED_SOURCE_DRAFT" | "SUPERSEDED_DRAFT";
  mode: "AUTOMATIC" | "MANUAL";
  foldCount: number;
  folds: SplitFold[];
  selectedFeatureSetIds: string[];
  windowPolicy: "EXPANDING" | "ROLLING";
  embargoDays: number;
  minimumTrainingGames: number;
  minimumValidationGames: number;
  allowGaps: boolean;
  groupingUnit: "CANONICAL_GAME";
  dateAtomic: true;
  classPolicy: string;
  preprocessingScope: string;
  deterministicSeed: number;
  qualityGates: SplitQualityGate[];
  checksum: string;
  notes: string;
  createdAt: string;
};

export type SplitContractState = {
  expectedChecksum: string;
  draft: SplitContractVersion | null;
  registered: SplitContractVersion | null;
  history: SplitContractVersion[];
};

export type SplitStudioData = {
  summary: {
    developmentRows: number;
    developmentGames: number;
    developmentDates: number;
    developmentStart: string;
    developmentEnd: string;
    finalOotRows: number;
    finalOotStart: string;
    finalOotEnd: string;
    finalOotLocked: boolean;
    foldCount: number;
    groupingUnit: string;
    datePolicy: string;
    trainingPolicy: string;
    classPolicy: string;
  };
  targetDistribution: { class: string; rows: number; percent: number }[];
  recommendedDesign: {
    mode: "AUTOMATIC" | "MANUAL";
    foldCount: number;
    windowPolicy: "EXPANDING" | "ROLLING";
    embargoDays: number;
    minimumTrainingGames: number;
    minimumValidationGames: number;
    deterministicSeed: number;
    selectedFeatureSetIds: string[];
  };
  folds: SplitFold[];
  qualityGates: SplitQualityGate[];
  contractState: SplitContractState;
};

function assertSafe<T>(value: StudioEnvelope<T>, projectId: string): StudioEnvelope<T> {
  const activity = value?.audit?.modelActivity;
  const safe = Boolean(
    value?.ok
      && value.authority?.projectId === projectId
      && value.population?.scope === "DEVELOPMENT_ONLY"
      && value.population?.finalOotLocked
      && value.audit?.finalOotTargetAccessed === false
      && value.audit?.finalOotUsedForSelection === false
      && value.audit?.legacyGlobalMatrixUsed === false
      && value.audit?.providerCalls === 0
      && activity
      && Object.values(activity).every((count) => count === 0),
  );
  if (!safe) throw new Error("The Stage 3 response did not preserve project authority, the final-OOT lock, and zero model activity.");
  return value;
}

function normalizedFeatureSetVersion(raw: any): FeatureSetVersion {
  const outlier = raw?.treatmentPolicies?.outlier ?? {};
  const missing = raw?.treatmentPolicies?.missing ?? {};
  return {
    featureSetId: String(raw?.featureSetId ?? ""),
    featureSetKey: String(raw?.featureSetKey ?? "PROJECT_CANDIDATE_FEATURE_SET"),
    version: Number(raw?.version ?? 0),
    status: raw?.status ?? "DRAFT",
    name: String(raw?.name ?? raw?.featureSetKey ?? "Feature set"),
    description: String(raw?.description ?? ""),
    orderedFeatures: Array.isArray(raw?.orderedFeatures) ? raw.orderedFeatures : [],
    activeFeatureCount: Array.isArray(raw?.orderedFeatures) ? raw.orderedFeatures.length : 0,
    unavailableExclusions: Array.isArray(raw?.unavailableExclusions) ? raw.unavailableExclusions : [],
    transformationContracts: raw?.transformationContracts ?? {},
    interactionContracts: Object.fromEntries((raw?.interactionContracts ?? []).map((item: any) => [item.name, item.status])),
    outlierPolicyId: String(outlier?.policyId ?? "NOT_ADOPTED"),
    missingPolicyId: String(missing?.policyId ?? "NOT_ADOPTED"),
    checksum: String(raw?.checksum ?? ""),
    notes: String(raw?.notes ?? ""),
    createdAt: String(raw?.createdAt ?? ""),
  };
}

function normalizedFeatureSetState(raw: any): FeatureSetState {
  const value = raw?.featureSetState ?? raw?.state ?? raw ?? {};
  const registered = value.registeredSets ?? (value.registered ? [value.registered] : []);
  return {
    expectedChecksum: String(value.expectedChecksum ?? "NO_CURRENT_FEATURE_SET"),
    draft: value.draft ? normalizedFeatureSetVersion(value.draft) : null,
    registered: registered.map(normalizedFeatureSetVersion),
    history: (value.history ?? []).map(normalizedFeatureSetVersion),
  };
}

function normalizedFamily(raw: any): FeatureFamily {
  const missing = raw?.physicalMissingness?.meanDevelopmentPercent;
  const rawName = String(raw?.name ?? raw?.familyId ?? "UNKNOWN_FAMILY");
  const familyId = rawName.replace(/^[A-G]\s+/, "");
  return {
    familyId,
    friendlyName: String(raw?.friendlyName ?? raw?.name ?? "Feature family"),
    orderedFeatures: raw?.orderedFeatures ?? [],
    featureCount: Number(raw?.featureCount ?? 0),
    eligibleFeatureCount: Number(raw?.eligibleFeatureCount ?? 0),
    inactiveFeatureCount: Number(raw?.inactiveFeatureCount ?? 0),
    unavailableFeatureCount: Number(raw?.sourceUnavailableCount ?? 0),
    physicalMissingPercent: missing == null ? null : Number(missing),
    sourceUnavailableCount: Number(raw?.sourceUnavailableCount ?? 0),
    coldStartExposurePercent: raw?.coldStartExposure?.percent == null ? null : Number(raw.coldStartExposure.percent),
    pointInTimeStatus: String(raw?.pointInTimeStatus ?? "PROJECT_BOUND_POINT_IN_TIME"),
    forecastTimeAvailability: String(raw?.forecastTimeStatus ?? "PREGAME_OR_SIMULATOR_SUPPLIED_AS_DECLARED"),
    interactionCount: Number(raw?.interactionCount ?? 0),
    modelCompatibility: Array.isArray(raw?.modelCompatibility) ? raw.modelCompatibility : [String(raw?.transformationCompatibility ?? "PER_FEATURE")],
    governanceWarnings: raw?.warnings ?? [],
    excludedFeatures: (raw?.excludedReasons ?? []).map((item: any) => ({ feature: String(item.feature ?? item.name ?? "unavailable"), reason: String(item.reason ?? item) })),
    selected: Boolean(raw?.selected),
  };
}

function normalizedParentTreatmentAuthorities(
  raw: unknown,
): GovernedInteractionParentTreatmentAuthority[] {
  if (Array.isArray(raw)) {
    return raw.filter(
      (value): value is GovernedInteractionParentTreatmentAuthority =>
        typeof value === "string" || Boolean(value && typeof value === "object"),
    );
  }
  if (raw && typeof raw === "object") {
    return Object.entries(raw as Record<string, unknown>).map(
      ([parentFeature, authority]) =>
        authority && typeof authority === "object"
          ? { parentFeature, ...(authority as Record<string, unknown>) }
          : `${parentFeature}: ${String(authority ?? "NOT_REPORTED")}`,
    );
  }
  return [];
}

function normalizedInteractionAuthority(
  raw: any,
): GovernedInteractionAuthority | null {
  if (!raw || typeof raw !== "object") return null;
  return {
    featureName: String(
      raw.featureName ??
        raw.interactionFeature ??
        raw.interactionFeatureName ??
        raw.feature ??
        raw.name ??
        "",
    ),
    backendFeatureIdentity: String(
      raw.backendFeatureIdentity ?? raw.featureName ?? raw.feature ?? raw.name ?? "",
    ),
    formula: String(raw.formula ?? "NOT_REGISTERED"),
    formulaVersion: String(raw.formulaVersion ?? "NOT_REGISTERED"),
    orderedParents: normalizedStringList(
      raw.orderedParents ?? raw.parentFeatures ?? raw.parentVariables,
    ),
    parentTreatmentAuthorities: normalizedParentTreatmentAuthorities(
      raw.parentTreatmentAuthorities ??
        (Array.isArray(raw.parents)
          ? raw.parents.map(
              (parent: any) => parent?.parentTreatmentAuthority ?? parent,
            )
          : undefined),
    ),
    operationOrder: normalizedStringList(
      raw.operationOrder ?? raw.transformationOrder,
    ),
    pointInTime: String(
      raw.pointInTime ?? raw.pointInTimeStatus ?? "NOT_REPORTED",
    ).toUpperCase(),
    foldLocal: String(
      raw.foldLocal ?? raw.foldLocalStatus ?? "NOT_REPORTED",
    ).toUpperCase(),
    status: String(raw.status ?? raw.executableStatus ?? "NOT_REPORTED"),
    blockedReason:
      raw.blockedReason == null ? null : String(raw.blockedReason),
  };
}

function normalizedInteractionAuthoritySummary(
  raw: any,
): GovernedInteractionAuthoritySummary | null {
  if (!raw || typeof raw !== "object") return null;
  return {
    authorityName: String(raw.authorityName ?? "NOT_REPORTED"),
    authorityId: String(raw.authorityId ?? "NOT_REPORTED"),
    authorityChecksum: String(raw.authorityChecksum ?? "NOT_REPORTED"),
    foldLocal: String(raw.foldLocal ?? "NOT_REPORTED").toUpperCase(),
    pointInTime: String(raw.pointInTime ?? "NOT_REPORTED").toUpperCase(),
    featureCount: raw.featureCount == null ? null : Number(raw.featureCount),
    readyFeatureCount:
      raw.readyFeatureCount == null ? null : Number(raw.readyFeatureCount),
    blockedFeatureCount:
      raw.blockedFeatureCount == null ? null : Number(raw.blockedFeatureCount),
    bindings: (Array.isArray(raw.bindings) ? (raw.bindings as unknown[]) : [])
      .map((binding: unknown) => normalizedInteractionAuthority(binding))
      .filter(
        (
          value: GovernedInteractionAuthority | null,
        ): value is GovernedInteractionAuthority => value !== null,
      ),
  };
}

function normalizedInteraction(raw: any): InteractionContract {
  const governed = normalizedInteractionAuthority(
    raw?.interactionAuthority ??
      raw?.authorityBinding ??
      (raw?.formulaVersion || raw?.orderedParents || raw?.operationOrder
        ? raw
        : null),
  );
  return {
    name: String(raw?.name ?? "interaction"),
    status: String(governed?.status ?? raw?.status ?? "INACTIVE"),
    reason: String(raw?.reason ?? ""),
    parentVariables: normalizedStringList(
      raw?.parentVariables ?? raw?.selectedPhysicalFeatures,
    ),
    formula: String(governed?.formula ?? raw?.formula ?? ""),
    formulaVersion: String(
      governed?.formulaVersion ?? raw?.formulaVersion ?? "",
    ),
    orderedParents: governed?.orderedParents.length
      ? governed.orderedParents
      : normalizedStringList(raw?.orderedParents ?? raw?.parentVariables),
    parentTreatmentAuthorities: governed?.parentTreatmentAuthorities.length
      ? governed.parentTreatmentAuthorities
      : normalizedParentTreatmentAuthorities(raw?.parentTreatmentAuthorities),
    operationOrder: governed?.operationOrder.length
      ? governed.operationOrder
      : normalizedStringList(raw?.operationOrder),
    coveragePercent: raw?.coveragePercent == null ? null : Number(raw.coveragePercent),
    missingPercent: raw?.missingPercent == null ? null : Number(raw.missingPercent),
    pointInTimeStatus: String(
      governed?.pointInTime ??
        raw?.pointInTimeStatus ??
        "PROJECT_BOUND_POINT_IN_TIME",
    ),
    foldLocal: String(governed?.foldLocal ?? raw?.foldLocal ?? "NOT_REPORTED"),
    executableStatus: String(
      governed?.status ?? raw?.executableStatus ?? raw?.status ?? "NOT_REPORTED",
    ),
    blockedReason:
      governed?.blockedReason ??
      (raw?.blockedReason == null ? null : String(raw.blockedReason)),
    selectedCandidateSets: raw?.selectedCandidateSets ?? [],
  };
}

function normalizedStringList(raw: unknown): string[] {
  if (Array.isArray(raw)) {
    return raw
      .filter((value): value is string => typeof value === "string")
      .map((value) => value.trim())
      .filter(Boolean);
  }
  if (raw && typeof raw === "object") {
    return Object.values(raw as Record<string, unknown>)
      .filter((value): value is string => typeof value === "string")
      .map((value) => value.trim())
      .filter(Boolean);
  }
  return typeof raw === "string" && raw.trim() ? [raw.trim()] : [];
}

function isGovernedPriorStatus(status: string): boolean {
  return (
    status === GOVERNED_PRIOR_EXECUTABLE_STATUS ||
    status === GOVERNED_PRIOR_BINDING_READY_STATUS ||
    status === GOVERNED_PRIOR_RETIRED_STATUS ||
    status === GOVERNED_PRIOR_BLOCKED_STATUS
  );
}

function normalizedPriorAuthority(
  raw: any,
  derivedOutputs?: unknown,
): GovernedPreprocessingPriorAuthority | null {
  if (!raw || typeof raw !== "object") return null;
  const hierarchy = normalizedStringList(raw.hierarchy);
  const status = String(raw.status ?? "SUMMARY");
  return {
    featureName:
      raw.featureName == null && raw.feature == null
        ? undefined
        : String(raw.featureName ?? raw.feature),
    authorityName: String(raw.authorityName ?? "NOT_REPORTED"),
    authorityId: String(raw.authorityId ?? "NOT_REPORTED"),
    method: String(raw.method ?? "NOT_REPORTED"),
    hierarchy,
    exposureFeature:
      raw.exposureFeature == null ? null : String(raw.exposureFeature),
    exposureDefinition: String(raw.exposureDefinition ?? ""),
    reliability: String(raw.reliability ?? "NOT_REPORTED"),
    foldLocal: String(raw.foldLocal ?? "NOT_REPORTED").toUpperCase(),
    pointInTime: String(raw.pointInTime ?? "NOT_REPORTED").toUpperCase(),
    status,
    executable: status === GOVERNED_PRIOR_EXECUTABLE_STATUS,
    selectable: status === GOVERNED_PRIOR_EXECUTABLE_STATUS,
    blockedReason:
      raw.blockedReason == null ? null : String(raw.blockedReason),
    resolution: raw.resolution == null ? null : String(raw.resolution),
    retirementReason:
      raw.retirementReason == null ? null : String(raw.retirementReason),
    derivedOutputs: normalizedStringList(
      derivedOutputs ?? raw.derivedOutputs ?? raw.derivedOutputMap,
    ),
    readyFeatureCount:
      raw.readyFeatureCount == null ? null : Number(raw.readyFeatureCount),
    bindingReadyRequiresWave2EngineFeatureCount:
      raw.bindingReadyRequiresWave2EngineFeatureCount == null &&
      raw.bindingReadyFeatureCount == null
        ? null
        : Number(
            raw.bindingReadyRequiresWave2EngineFeatureCount ??
              raw.bindingReadyFeatureCount,
          ),
    retiredFeatureCount:
      raw.retiredFeatureCount == null ? null : Number(raw.retiredFeatureCount),
    blockedFeatureCount:
      raw.blockedFeatureCount == null ? null : Number(raw.blockedFeatureCount),
    featureCount: raw.featureCount == null ? null : Number(raw.featureCount),
    bindings: (Array.isArray(raw.bindings) ? raw.bindings : [])
      .map((binding: unknown) => normalizedPriorAuthority(binding))
      .filter(
        (
          binding: GovernedPreprocessingPriorAuthority | null,
        ): binding is GovernedPreprocessingPriorAuthority => binding !== null,
      ),
  };
}

function normalizedTreatmentSpecificationResolution(
  raw: any,
): TreatmentSpecificationResolution | null {
  if (!raw || typeof raw !== "object") return null;
  const derivedPriorOutputs = normalizedStringList(raw.derivedPriorOutputs);
  const executableStatus = String(
    raw.executableStatus ?? raw.executable_status ?? "NOT_REPORTED",
  );
  const nestedPriorStatus = String(raw.priorAuthority?.status ?? "");
  const governedPriorStatus =
    isGovernedPriorStatus(executableStatus) ||
    isGovernedPriorStatus(nestedPriorStatus);
  const effectivePriorStatus = isGovernedPriorStatus(executableStatus)
    ? executableStatus
    : nestedPriorStatus;
  const retirementReason =
    raw.priorAuthority?.retirementReason == null
      ? null
      : String(raw.priorAuthority.retirementReason);
  return {
    executableStatus,
    executable: governedPriorStatus
      ? effectivePriorStatus === GOVERNED_PRIOR_EXECUTABLE_STATUS
      : raw.executable === true || raw.execution_contract?.executable === true,
    executableSelectable: governedPriorStatus
      ? effectivePriorStatus === GOVERNED_PRIOR_EXECUTABLE_STATUS
      : raw.executableSelectable === true || raw.executable_selectable === true,
    blockedReason: raw.blockedReason == null ? null : String(raw.blockedReason),
    resolution: raw.resolution == null ? null : String(raw.resolution),
    retirementReason,
    scientificRecommendation: String(
      raw.scientificRecommendation ?? "NOT_REPORTED",
    ),
    priorAuthority: normalizedPriorAuthority(
      raw.priorAuthority,
      derivedPriorOutputs,
    ),
    interactionAuthority: normalizedInteractionAuthority(
      raw.interactionAuthority,
    ),
    derivedPriorOutputs,
  };
}

function normalizedTreatmentSpecificationDraft(
  raw: any,
): TreatmentSpecificationDraftAuthority | null {
  if (!raw || typeof raw !== "object") return null;
  return {
    specificationDraftId: String(raw.specificationDraftId ?? ""),
    specificationVersion:
      raw.specificationVersion == null
        ? null
        : Number(raw.specificationVersion),
    manifestChecksum: String(raw.manifestChecksum ?? ""),
    status: String(raw.status ?? "DRAFT"),
    priorAuthority: normalizedPriorAuthority(raw.priorAuthority),
    interactionAuthority: normalizedInteractionAuthoritySummary(
      raw.interactionAuthority,
    ),
    executionSummary:
      raw.executionSummary && typeof raw.executionSummary === "object"
        ? raw.executionSummary
        : {},
  };
}

function normalizedFeatureRow(raw: any): FeatureInventoryRow {
  const min = raw?.minimum;
  const max = raw?.maximum;
  const range = min == null && max == null ? String(raw?.cardinalityRangeStatus ?? "DETAIL_ON_DEMAND") : `${min ?? "—"} → ${max ?? "—"}`;
  return {
    order: Number(raw?.order ?? 0),
    featureName: String(raw?.name ?? raw?.featureName ?? ""),
    friendlyLabel: String(raw?.label ?? raw?.friendlyLabel ?? raw?.name ?? "Feature"),
    family: String(raw?.featureFamily ?? raw?.family ?? "UNASSIGNED"),
    core: Boolean(raw?.core),
    dataType: String(raw?.dataType ?? "unknown"),
    role: String(raw?.role ?? "PREGAME_FEATURE"),
    definition: String(raw?.definition ?? "Definition is registered with the accepted feature contract."),
    sourceLineage: String(raw?.sourceLineage ?? ""),
    earliestAvailableDate: raw?.earliestDevelopmentDate ?? null,
    latestDevelopmentDate: String(raw?.latestDevelopmentDate ?? "2026-08-13"),
    developmentCoveragePercent: raw?.coverageDevelopment == null ? null : Number(raw.coverageDevelopment) * 100,
    physicalMissingPercent: raw?.physicalMissingnessPercent == null ? null : Number(raw.physicalMissingnessPercent),
    coldStartRelevant: String(raw?.coldStartRelevance ?? "").includes("COLD_START") || String(raw?.coldStartRelevance ?? "").includes("HISTORY"),
    outlierPrevalencePercent: raw?.adoptedOutlierPrevalencePercent == null ? null : Number(raw.adoptedOutlierPrevalencePercent),
    missingValueTreatment: String(raw?.adoptedMissingTreatment ?? "NOT_ADOPTED"),
    outlierTreatment: String(raw?.adoptedOutlierTreatment ?? "NOT_ADOPTED"),
    pointInTimeTreatment: String(raw?.pointInTimeTreatment ?? ""),
    forecastTimeAvailability: String(raw?.forecastTimeAvailability ?? raw?.availabilityStatus ?? ""),
    simulationGeneratedState: Boolean(raw?.simulationGeneratedState),
    leakageRisk: String(raw?.leakageRisk ?? "NONE_DECLARED"),
    cardinality: raw?.cardinality == null ? null : Number(raw.cardinality),
    range,
    interactionMembership: raw?.interactionMembership ?? [],
    status: raw?.featureState ?? (raw?.eligible ? "ACTIVE" : "INACTIVE"),
    unavailableReason: raw?.unavailableReason ?? raw?.inactiveReason ?? null,
    selectedCandidateSets: raw?.selectedFeatureSetIds ?? [],
    eligibleTransformations: raw?.compatibleTransformations ?? [],
    selectedTransformation: String(raw?.selectedTransformation ?? "RETAIN_RAW"),
    treatmentSpecificationResolution:
      normalizedTreatmentSpecificationResolution(
        raw?.treatmentSpecificationResolution,
      ),
    targetClassComparison: raw?.targetClassComparison?.rows ?? [],
    temporalCoverage: raw?.temporalCoverage ?? [],
    missingnessBySeason: (raw?.missingnessBySeason ?? []).map((item: any) => ({ label: String(item.season ?? item.label), value: Number(item.missingPercent ?? item.value ?? 0) })),
    missingnessByMonth: (raw?.missingnessByMonth ?? []).map((item: any) => ({ label: String(item.month ?? item.label), value: Number(item.missingPercent ?? item.value ?? 0) })),
    redundancy: raw?.redundancy?.rows ?? [],
  };
}

function normalizedFeatureSummary(raw: any): FeatureStudioSummary {
  const families = (raw?.families ?? []).map(normalizedFamily);
  const counts = raw?.summary?.interactionCounts ?? {};
  const interactionRows = (raw?.interactions ?? []).map(normalizedInteraction);
  const familyCoverage = families.map((item: FeatureFamily) => ({ family: item.friendlyName, coveragePercent: item.physicalMissingPercent == null ? 0 : Math.max(0, 100 - item.physicalMissingPercent) }));
  const familyMissingness = families.map((item: FeatureFamily) => ({ family: item.friendlyName, missingPercent: item.physicalMissingPercent ?? 0 }));
  const treatmentSpecificationDraft = normalizedTreatmentSpecificationDraft(
    raw?.treatmentSpecificationDraft,
  );
  return {
    summary: {
      coreFeatureCount: Number(raw?.summary?.coreFeatureCount ?? 0),
      contextualFeatureCount: Number(raw?.summary?.contextualFeatureCount ?? 0),
      totalCandidateCount: Number(raw?.summary?.totalCandidateCount ?? 0),
      eligibleContextualCount: Number(raw?.summary?.eligibleContextualCount ?? 0),
      inactiveFeatureCount: Number(raw?.summary?.inactiveFeatureCount ?? 0),
      unavailableFeatureCount: Number(raw?.summary?.unavailableFeatureCount ?? 0),
      familyCount: Number(raw?.summary?.familyCount ?? families.length),
      interactionCount: Number(counts.total ?? interactionRows.length),
      materializedInteractionCount: Number(counts.materialized ?? 0),
      inactiveInteractionCount: Number(counts.inactivePendingRivalry ?? 0),
      unavailableInteractionCount: Number(counts.sourceUnavailable ?? 0),
      finalOotRows: Number(raw?.summary?.finalOotRows ?? 0),
      finalOotLocked: Boolean(raw?.summary?.finalOotLocked),
      selectedCandidateSetCount: Number(raw?.summary?.selectedCandidateSetCount ?? 0),
    },
    families,
    interactions: interactionRows,
    recommendedSets: (raw?.recommendedSets ?? []).map((item: any) => ({
      setId: String(item.setId),
      name: String(item.name),
      description: String(item.description ?? ""),
      orderedFeatures: item.orderedFeatures ?? [],
      activeFeatureCount: Number(item?.counts?.total ?? item.activeFeatureCount ?? 0),
      unavailableExclusions: (item.exclusions ?? []).map((entry: any) => ({ feature: String(entry.feature ?? entry.name ?? "unavailable"), reason: String(entry.reason ?? entry) })),
      transformationContracts: item.defaultTransformationContracts ?? {},
      interactionContracts: Object.fromEntries((item.interactionContracts ?? []).map((entry: any) => [entry.name, entry.status])),
    })),
    treatmentPolicies: {
      outlier: {
        policyId: String(raw?.treatmentPolicies?.outlier?.policyId ?? "NOT_ADOPTED"),
        version: Number(raw?.treatmentPolicies?.outlier?.policyVersion ?? 0),
        checksum: String(raw?.treatmentPolicies?.outlier?.checksum ?? ""),
      },
      missing: {
        policyId: String(raw?.treatmentPolicies?.missing?.policyId ?? "NOT_ADOPTED"),
        version: Number(raw?.treatmentPolicies?.missing?.policyVersion ?? 0),
        checksum: String(raw?.treatmentPolicies?.missing?.checksum ?? ""),
      },
    },
    visualizations: { familyCoverage, familyMissingness, featureAvailabilityBySeason: [] },
    treatmentSpecificationDraft,
    priorAuthority:
      normalizedPriorAuthority(raw?.priorAuthority) ??
      treatmentSpecificationDraft?.priorAuthority ??
      null,
    interactionAuthority:
      normalizedInteractionAuthoritySummary(raw?.interactionAuthority) ??
      treatmentSpecificationDraft?.interactionAuthority ??
      null,
    featureSetState: normalizedFeatureSetState(raw?.featureSetState),
  };
}

function normalizedDistribution(raw: any): { class: string; rows: number; percent: number }[] {
  return (Array.isArray(raw) ? raw : []).map((item: any) => ({
    class: String(item?.class ?? item?.value ?? "UNKNOWN"),
    rows: Number(item?.rows ?? item?.count ?? 0),
    percent: Number(item?.percent ?? 0),
  }));
}

function normalizedSplitFold(raw: any): SplitFold {
  const training = raw?.training ?? {};
  const validation = raw?.validation ?? {};
  const selectedIds = raw?.selectedFeatureSetIds ?? [];
  return {
    foldNumber: Number(raw?.foldNumber ?? 0),
    trainingStart: String(raw?.trainingStart ?? raw?.trainStart ?? training?.startDate ?? ""),
    trainingEnd: String(raw?.trainingEnd ?? raw?.trainEnd ?? training?.endDate ?? ""),
    validationStart: String(raw?.validationStart ?? validation?.startDate ?? ""),
    validationEnd: String(raw?.validationEnd ?? validation?.endDate ?? ""),
    trainRows: Number(raw?.trainRows ?? training?.rows ?? 0),
    validationRows: Number(raw?.validationRows ?? validation?.rows ?? 0),
    trainGames: Number(raw?.trainGames ?? training?.games ?? 0),
    validationGames: Number(raw?.validationGames ?? validation?.games ?? 0),
    distinctValidationDates: Number(raw?.distinctValidationDates ?? raw?.validationDates ?? validation?.dates ?? 0),
    batters: Number(raw?.batters ?? raw?.validationBatters ?? validation?.batters ?? 0),
    pitchers: Number(raw?.pitchers ?? raw?.validationPitchers ?? validation?.pitchers ?? 0),
    coldStartPercent: Number(raw?.coldStartPercent ?? validation?.coldStart?.percent ?? 0),
    physicalMissingPercent: Number(raw?.physicalMissingPercent ?? validation?.physicalMissingness?.missingCellPercent ?? 0),
    trainingClassDistribution: normalizedDistribution(raw?.trainingClassDistribution ?? training?.classDistribution),
    validationClassDistribution: normalizedDistribution(raw?.validationClassDistribution ?? validation?.classDistribution),
    featureSetAvailability: selectedIds.map((featureSetId: string) => ({ featureSetId, available: true, reason: "Exact registered feature-set version bound" })),
    preprocessingFitScope: String(raw?.preprocessingFitScope ?? "TRAINING_ROWS_OF_THIS_FOLD_ONLY"),
    checksum: String(raw?.checksum ?? ""),
  };
}

function normalizedSplitGate(raw: any): SplitQualityGate {
  const code = String(raw?.code ?? "UNKNOWN_GATE");
  return {
    code,
    label: String(raw?.label ?? code.replaceAll("_", " ").toLowerCase().replace(/\b\w/g, (letter) => letter.toUpperCase())),
    passed: raw?.passed === true || raw?.status === "PASS",
    blocking: raw?.blocking !== false,
    detail: String(raw?.detail ?? ""),
  };
}

function normalizedSplitContractVersion(raw: any): SplitContractVersion {
  const contract = raw?.contract ?? raw ?? {};
  const trainingPolicy = String(contract?.trainingPolicy ?? "EXPANDING_WINDOW");
  return {
    splitContractId: String(raw?.splitContractId ?? raw?.contractId ?? ""),
    version: Number(raw?.version ?? raw?.contractVersion ?? 0),
    status: raw?.status ?? "DRAFT",
    mode: String(raw?.mode ?? raw?.splitMode ?? contract?.mode ?? "AUTOMATIC") as "AUTOMATIC" | "MANUAL",
    foldCount: Number(raw?.foldCount ?? contract?.foldCount ?? 0),
    folds: (raw?.folds ?? contract?.folds ?? []).map(normalizedSplitFold),
    selectedFeatureSetIds: raw?.selectedFeatureSetIds ?? contract?.selectedFeatureSetIds ?? [],
    windowPolicy: (trainingPolicy === "ROLLING_WINDOW" ? "ROLLING" : "EXPANDING") as "EXPANDING" | "ROLLING",
    embargoDays: Number(contract?.embargoDays ?? 0),
    minimumTrainingGames: Number(contract?.minimumTrainingGames ?? 0),
    minimumValidationGames: Number(contract?.minimumValidationGames ?? 0),
    allowGaps: Boolean(contract?.allowGaps),
    groupingUnit: "CANONICAL_GAME",
    dateAtomic: true,
    classPolicy: String(contract?.classPolicy?.strategy ?? contract?.classPolicy ?? "NATURAL_BASE_RATES"),
    preprocessingScope: String(contract?.preprocessingScope ?? "FIT_INSIDE_EACH_TRAINING_FOLD_ONLY"),
    deterministicSeed: Number(contract?.deterministicSeed ?? 0),
    qualityGates: (contract?.qualityGates ?? []).map(normalizedSplitGate),
    checksum: String(raw?.checksum ?? contract?.checksum ?? ""),
    notes: String(raw?.notes ?? ""),
    createdAt: String(raw?.createdAt ?? ""),
  };
}

function normalizedSplitState(raw: any): SplitContractState {
  const value = raw?.contractState ?? raw?.state ?? raw ?? {};
  return {
    expectedChecksum: String(value?.expectedChecksum ?? NO_CURRENT_SPLIT_CONTRACT),
    draft: value?.latestDraft ? normalizedSplitContractVersion(value.latestDraft) : value?.draft ? normalizedSplitContractVersion(value.draft) : null,
    registered: value?.currentRegistered ? normalizedSplitContractVersion(value.currentRegistered) : value?.registered ? normalizedSplitContractVersion(value.registered) : null,
    history: (value?.history ?? []).map(normalizedSplitContractVersion),
  };
}

function normalizedSplitStudio(raw: any): SplitStudioData {
  const summary = raw?.summary ?? {};
  const design = raw?.recommendedDesign ?? raw?.design ?? {};
  return {
    summary: {
      developmentRows: Number(summary?.developmentRows ?? 0),
      developmentGames: Number(summary?.developmentGames ?? 0),
      developmentDates: Number(summary?.developmentDates ?? 0),
      developmentStart: String(summary?.developmentStart ?? ""),
      developmentEnd: String(summary?.developmentEnd ?? ""),
      finalOotRows: Number(summary?.finalOotRows ?? 0),
      finalOotStart: String(summary?.finalOotStart ?? ""),
      finalOotEnd: String(summary?.finalOotEnd ?? ""),
      finalOotLocked: Boolean(summary?.finalOotLocked),
      foldCount: Number(summary?.foldCount ?? summary?.folds ?? design?.foldCount ?? 0),
      groupingUnit: String(summary?.groupingUnit ?? "CANONICAL_GAME"),
      datePolicy: String(summary?.datePolicy ?? "DATE_ATOMIC"),
      trainingPolicy: String(summary?.trainingPolicy ?? design?.trainingPolicy ?? "EXPANDING_WINDOW"),
      classPolicy: String(summary?.classPolicy ?? design?.classPolicy?.strategy ?? "NATURAL_BASE_RATES"),
    },
    targetDistribution: normalizedDistribution(raw?.targetDistribution),
    recommendedDesign: {
      mode: String(design?.mode ?? "AUTOMATIC") as "AUTOMATIC" | "MANUAL",
      foldCount: Number(design?.foldCount ?? 5),
      windowPolicy: (design?.trainingPolicy === "ROLLING_WINDOW" ? "ROLLING" : "EXPANDING") as "EXPANDING" | "ROLLING",
      embargoDays: Number(design?.embargoDays ?? 0),
      minimumTrainingGames: Number(design?.minimumTrainingGames ?? 1),
      minimumValidationGames: Number(design?.minimumValidationGames ?? 1),
      deterministicSeed: Number(design?.deterministicSeed ?? 0),
      selectedFeatureSetIds: design?.selectedFeatureSetIds ?? [],
    },
    folds: (raw?.folds ?? design?.folds ?? []).map(normalizedSplitFold),
    qualityGates: (raw?.qualityGates ?? design?.qualityGates ?? []).map(normalizedSplitGate),
    contractState: normalizedSplitState(raw?.contractState),
  };
}

const featurePrefix = (projectId: string) => `/projects/${encodeURIComponent(projectId)}/sports/stage3-feature-engineering`;
const splitPrefix = (projectId: string) => `/projects/${encodeURIComponent(projectId)}/sports/stage3-split-balance`;

async function postJSONWithExactError<T>(path: string, body: Record<string, unknown>, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method: "POST",
    body: JSON.stringify(body),
    signal,
    headers: { "Content-Type": "application/json", Accept: "application/json" },
  });
  const value = await response.json().catch(() => null) as any;
  if (!response.ok) {
    const detail = value?.detail;
    const code = typeof detail === "object" ? String(detail?.code || "") : "";
    const message = typeof detail === "object" ? String(detail?.message || "") : typeof detail === "string" ? detail : "";
    throw new Error([code, message].filter(Boolean).join(": ") || `POST ${path} failed: ${response.status}`);
  }
  return value as T;
}

export async function fetchFeatureStudioSummary(projectId: string, signal?: AbortSignal) {
  const value = assertSafe(await getJSON<StudioEnvelope<any>>(`${featurePrefix(projectId)}/summary`, { signal }), projectId);
  return { ...value, data: normalizedFeatureSummary(value.data) } as StudioEnvelope<FeatureStudioSummary>;
}

export async function fetchFeatureInventory(projectId: string, query: Record<string, unknown>, signal?: AbortSignal) {
  const sortMap: Record<string, string> = {
    order: "order",
    featureName: "name",
    family: "featureFamily",
    dataType: "dataType",
    developmentCoveragePercent: "coverageDevelopment",
    physicalMissingPercent: "missingPercentDevelopment",
    outlierPrevalencePercent: "adoptedOutlierTreatment",
    status: "governanceStatus",
  };
  const dataType = String(query.dataType ?? "").toUpperCase();
  const featureStatus = String(query.status ?? "").toUpperCase();
  const forecastAvailability = {
    AVAILABLE: "PREGAME",
    SIMULATOR_SUPPLIED: "SIMULATOR",
  }[String(query.forecastAvailability ?? "").toUpperCase()] ?? query.forecastAvailability;
  const normalizedQuery = {
    ...query,
    forecastAvailability,
    families: query.family ? [query.family] : [],
    statuses: query.governanceStatus ? [query.governanceStatus] : [],
    governanceStatuses: query.governanceStatus ? [query.governanceStatus] : [],
    featureStates: featureStatus && featureStatus !== "UNAVAILABLE" ? [featureStatus] : [],
    dataTypes: dataType && dataType !== "BINARY" ? [dataType.toLowerCase()] : [],
    binaryOnly: dataType === "BINARY",
    sortBy: sortMap[String(query.sortField)] ?? "order",
  };
  const value = assertSafe(await postJSON<StudioEnvelope<any>>(`${featurePrefix(projectId)}/inventory`, normalizedQuery, { signal }), projectId);
  return { ...value, data: { ...value.data, rows: (value.data?.rows ?? []).map(normalizedFeatureRow) } } as StudioEnvelope<FeatureInventory>;
}

export async function fetchFeatureDetail(projectId: string, featureName: string, signal?: AbortSignal) {
  const value = assertSafe(await getJSON<StudioEnvelope<any>>(`${featurePrefix(projectId)}/feature/${encodeURIComponent(featureName)}`, { signal }), projectId);
  const summary = value.data?.developmentSummary ?? {};
  const statistics = summary.statistics ?? {};
  const raw = {
    ...(value.data?.feature ?? {}),
    cardinality: summary.uniqueObserved,
    minimum: statistics.min,
    maximum: statistics.max,
    compatibleTransformations: value.data?.compatibleTransformations ?? [],
    missingnessBySeason: value.data?.missingnessBySeason ?? [],
    missingnessByMonth: value.data?.missingnessByMonth ?? [],
    targetClassComparison: value.data?.developmentOnlyTargetComparison,
    redundancy: value.data?.redundancyAssessment,
  };
  return { ...value, data: { feature: normalizedFeatureRow(raw) } } as StudioEnvelope<{ feature: FeatureInventoryRow }>;
}

export async function fetchFeatureSetState(projectId: string, signal?: AbortSignal) {
  const value = assertSafe(await getJSON<StudioEnvelope<any>>(`${featurePrefix(projectId)}/feature-sets`, { signal }), projectId);
  return { ...value, data: normalizedFeatureSetState(value.data) } as StudioEnvelope<FeatureSetState>;
}

export async function mutateFeatureSet(projectId: string, action: "draft" | "register" | "retire", payload: Record<string, unknown>, signal?: AbortSignal) {
  const value = assertSafe(await postJSON<StudioEnvelope<any>>(`${featurePrefix(projectId)}/feature-sets/${action}`, payload, { signal }), projectId);
  return { ...value, data: normalizedFeatureSetState(value.data) } as StudioEnvelope<FeatureSetState>;
}

export async function fetchSplitStudio(projectId: string, signal?: AbortSignal) {
  const value = assertSafe(await getJSON<StudioEnvelope<any>>(`${splitPrefix(projectId)}/summary`, { signal }), projectId);
  return { ...value, data: normalizedSplitStudio(value.data) } as StudioEnvelope<SplitStudioData>;
}

export async function generateAutomaticSplit(projectId: string, payload: Record<string, unknown>, signal?: AbortSignal) {
  const value = assertSafe(await postJSON<StudioEnvelope<any>>(`${splitPrefix(projectId)}/automatic`, payload, { signal }), projectId);
  return { ...value, data: normalizedSplitStudio(value.data) } as StudioEnvelope<SplitStudioData>;
}

export async function validateManualSplit(projectId: string, payload: Record<string, unknown>, signal?: AbortSignal) {
  const value = assertSafe(await postJSONWithExactError<StudioEnvelope<any>>(`${splitPrefix(projectId)}/manual/validate`, payload, signal), projectId);
  return { ...value, data: normalizedSplitStudio(value.data) } as StudioEnvelope<SplitStudioData>;
}

export async function fetchSplitContractState(projectId: string, signal?: AbortSignal) {
  const value = assertSafe(await getJSON<StudioEnvelope<any>>(`${splitPrefix(projectId)}/contracts`, { signal }), projectId);
  return { ...value, data: normalizedSplitState(value.data) } as StudioEnvelope<SplitContractState>;
}

export async function mutateSplitContract(projectId: string, action: "draft" | "register", payload: Record<string, unknown>, signal?: AbortSignal) {
  const value = assertSafe(await postJSON<StudioEnvelope<any>>(`${splitPrefix(projectId)}/contracts/${action}`, payload, { signal }), projectId);
  return { ...value, data: normalizedSplitState(value.data) } as StudioEnvelope<SplitContractState>;
}
