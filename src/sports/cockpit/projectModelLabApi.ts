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
    seed: number;
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
  modelFamilies: ModelLabFamily[];
  candidateMatrix: ModelLabCandidatePlan[];
  readiness: { ready: boolean; blockers: string[] };
  latestRun: ModelLabRun | null;
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

type SummaryEnvelope = { ok: true } & ProjectModelLabSummary;
type RunEnvelope = { ok: true; run: ModelLabRun };
type RunsEnvelope = { ok: true; runs: ModelLabRun[] };

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
    || run.candidates.some((item) => !summary.modelFamilies.some((family) => family.id === item.modelFamily) || (item.featureSetId != null && !summary.featureSets.some((featureSet) => featureSet.featureSetId === item.featureSetId)))
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
