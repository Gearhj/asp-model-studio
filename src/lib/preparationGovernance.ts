import {
  getEdaDocumentationState,
  type EdaDocumentationState,
} from "./edaDocumentationApi";
import { DATASET_API_BASE } from "./datasetLibrary";
import {
  assertExactDatasetIdentity,
  canonicalDatasetStorageKey,
  requireCanonicalDatasetIdentity,
  type CanonicalDatasetIdentity,
  type CanonicalDatasetIdentityInput,
} from "./datasetIdentity";

export const OUTLIER_METHODS_STORAGE_PREFIX =
  "modeling-tool-outlier-methods";
export const OUTLIER_GLOBAL_METHOD_STORAGE_PREFIX =
  "modeling-tool-outlier-global-method";
export const OUTLIER_RATIONALES_STORAGE_PREFIX =
  "atlas:outlier-rationales";
export const MISSING_POLICY_STORAGE_PREFIX =
  "modeling-tool-missing-config";
export const VALIDATION_DESIGN_DRAFT_STORAGE_PREFIX =
  "atlas-validation-design-draft-v2";
export const TRAINING_CONFIG_STORAGE_PREFIX =
  "modeling-tool-training-config";

export type CanonicalValidationDesignDraft = {
  foldMethod?: string;
  foldCount?: number;
  foldRepeats?: number;
  innerFoldCount?: number;
  foldLocalPreprocessing?: string;
  groupField?: string;
  timeField?: string;
  shuffleFolds?: boolean;
  balanceMethod?: string;
  minorityShare?: number;
  classWeightPolicy?: string;
  externalValidationMode?: string;
  testDatasetId?: string;
  testDatasetVersion?: string;
  testTargetField?: string;
  ootDatasetId?: string;
  ootDatasetVersion?: string;
  ootTargetField?: string;
};

export type CanonicalPreparationBrowserState = {
  identity: CanonicalDatasetIdentity;
  outlierMethods: Record<string, unknown>;
  outlierGlobalMethod: string;
  outlierRationales: Record<string, string>;
  missingPolicy: Record<string, unknown>;
  validationDraft: CanonicalValidationDesignDraft | null;
  trainingConfig: Record<string, unknown>;
  splitStrategy: "Requires exact Analysis Partition";
  balanceMethod: string;
  balanceRatio: string;
  kFolds: string;
};

function readScopedJson<T>(
  prefix: string,
  identity: CanonicalDatasetIdentity,
  fallback: T,
): T {
  if (typeof localStorage === "undefined") return fallback;
  try {
    const raw = localStorage.getItem(
      canonicalDatasetStorageKey(prefix, identity),
    );
    if (!raw) return fallback;
    return (JSON.parse(raw) as T) ?? fallback;
  } catch {
    return fallback;
  }
}

function readScopedText(
  prefix: string,
  identity: CanonicalDatasetIdentity,
): string {
  if (typeof localStorage === "undefined") return "";
  try {
    return (
      localStorage.getItem(canonicalDatasetStorageKey(prefix, identity)) ?? ""
    ).trim();
  } catch {
    return "";
  }
}

function browserRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function validationDesignDraft(
  value: unknown,
): CanonicalValidationDesignDraft | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const draft = value as Record<string, unknown>;
  const sanitized: CanonicalValidationDesignDraft = {};
  const copyText = (key: keyof CanonicalValidationDesignDraft) => {
    const candidate = draft[key];
    if (typeof candidate === "string" && candidate.trim()) {
      sanitized[key] = candidate.trim() as never;
    }
  };
  const copyNumber = (key: keyof CanonicalValidationDesignDraft) => {
    const candidate = draft[key];
    if (typeof candidate === "number" && Number.isFinite(candidate)) {
      sanitized[key] = candidate as never;
    }
  };

  // Browser drafts may preserve non-partition preferences only. Row membership,
  // holdout size, seeds, and split authority come exclusively from the durable
  // Analysis Partition contract and are intentionally absent from this allowlist.
  [
    "foldMethod",
    "foldLocalPreprocessing",
    "groupField",
    "timeField",
    "balanceMethod",
    "classWeightPolicy",
    "externalValidationMode",
    "testDatasetId",
    "testDatasetVersion",
    "testTargetField",
    "ootDatasetId",
    "ootDatasetVersion",
    "ootTargetField",
  ].forEach((key) => copyText(key as keyof CanonicalValidationDesignDraft));
  ["foldCount", "foldRepeats", "innerFoldCount", "minorityShare"].forEach(
    (key) => copyNumber(key as keyof CanonicalValidationDesignDraft),
  );
  if (typeof draft.shuffleFolds === "boolean") {
    sanitized.shuffleFolds = draft.shuffleFolds;
  }

  return Object.keys(sanitized).length ? sanitized : null;
}

/**
 * Loads predictive preparation preferences from one exact immutable dataset
 * version namespace. Global, project-only, previous-version, and legacy keys
 * are intentionally never consulted.
 */
export function loadCanonicalPreparationBrowserState(
  identityInput: CanonicalDatasetIdentityInput,
): CanonicalPreparationBrowserState {
  const identity = requireCanonicalDatasetIdentity(
    identityInput,
    "Preparation governance browser state identity",
  );
  const outlierMethods = browserRecord(
    readScopedJson(
      OUTLIER_METHODS_STORAGE_PREFIX,
      identity,
      {},
    ),
  );
  const rawRationales = browserRecord(
    readScopedJson(
      OUTLIER_RATIONALES_STORAGE_PREFIX,
      identity,
      {},
    ),
  );
  const outlierRationales = Object.fromEntries(
    Object.entries(rawRationales)
      .map(([feature, rationale]) => [
        feature,
        typeof rationale === "string" ? rationale : "",
      ])
      .filter(([, rationale]) => Boolean(rationale)),
  );
  const missingPolicy = browserRecord(
    readScopedJson(
      MISSING_POLICY_STORAGE_PREFIX,
      identity,
      {},
    ),
  );
  const validationDraftValue = readScopedJson<unknown>(
    VALIDATION_DESIGN_DRAFT_STORAGE_PREFIX,
    identity,
    null,
  );
  const validationDraft = validationDesignDraft(validationDraftValue);
  const trainingConfig = browserRecord(
    readScopedJson(
      TRAINING_CONFIG_STORAGE_PREFIX,
      identity,
      {},
    ),
  );
  const balanceMethod =
    typeof validationDraft?.balanceMethod === "string" &&
    validationDraft.balanceMethod.trim()
      ? validationDraft.balanceMethod.trim()
      : "Not documented";
  const balanceRatio =
    typeof validationDraft?.minorityShare === "number" &&
    Number.isFinite(validationDraft.minorityShare)
      ? String(validationDraft.minorityShare)
      : "";
  const kFolds =
    validationDraft?.foldMethod &&
    validationDraft.foldMethod !== "none" &&
    typeof validationDraft.foldCount === "number" &&
    Number.isFinite(validationDraft.foldCount)
      ? String(validationDraft.foldCount)
      : "";

  return {
    identity,
    outlierMethods,
    outlierGlobalMethod:
      readScopedText(OUTLIER_GLOBAL_METHOD_STORAGE_PREFIX, identity) ||
      "Not documented",
    outlierRationales,
    missingPolicy,
    validationDraft,
    trainingConfig,
    splitStrategy: "Requires exact Analysis Partition",
    balanceMethod,
    balanceRatio,
    kFolds,
  };
}

export type PreparationStage =
  | "outliers"
  | "missing_values"
  | "feature_engineering"
  | "validation_design"
  | "model_training";

export type CarryForwardDisposition = "draft" | "accepted" | "deferred";

export type PreparationCarryForwardItem = {
  findingId: string;
  title: string;
  destination: string;
  recommendation: string;
  suggestedTransformation: string;
  reviewerRationale: string;
  sourceStatus: string;
  disposition: CarryForwardDisposition;
};

export type PreparationDocumentationStatus =
  | "draft"
  | "confirmed"
  | "stale";

export type PreparationDocumentationState = {
  ok: boolean;
  project_id: string;
  dataset_id: string;
  dataset_version_id: string;
  /** Compatibility alias; it must mirror dataset_version_id. */
  dataset_version: string;
  target: string | null;
  predictor_manifest_id: string | null;
  documentation_version: string;
  status: PreparationDocumentationStatus;
  predictor_authorization: {
    authorized_predictors: string[];
    excluded_predictors: Record<string, string>;
    target_source_excluded: string[];
  };
  outliers: {
    status: PreparationDocumentationStatus;
    application: Record<string, unknown> | null;
  };
  missing_values: {
    status: PreparationDocumentationStatus;
    application: Record<string, unknown> | null;
    validation: Record<string, unknown> | null;
  };
  feature_engineering: {
    status: PreparationDocumentationStatus;
    manifest_version: string | null;
    manifest_hash: string;
    validation_status?: string;
    materialization_status?: string;
    materialization_hash?: string;
    materialized_manifest_hash?: string;
    confirmation_status?: string;
    confirmed_manifest_hash?: string;
    accepted_features: Array<Record<string, unknown>>;
    materialized_features: string[];
    pipeline_steps: Array<Record<string, unknown>>;
    execution_history?: Array<Record<string, unknown>>;
    split_status?: string;
  };
  validation_design: {
    status: PreparationDocumentationStatus;
    validation_design_id: string | null;
    design_version: string | null;
    strategy: string | null;
    development_dataset_version?: string;
    training_population_id?: string;
    holdout_population_id?: string;
    test_reference?: Record<string, unknown> | null;
    oot_reference?: Record<string, unknown> | null;
    cv_design?: Record<string, unknown>;
    fold_architecture?: Record<string, unknown>;
    balancing_policy?: Record<string, unknown>;
    completion_gates: Record<string, boolean>;
    validation_risks?: Array<Record<string, unknown>>;
    confirmation_actor?: Record<string, unknown> | string | null;
    confirmation_time?: string | null;
    stale_reasons?: string[];
  };
  model_training: {
    status: PreparationDocumentationStatus;
    training_job_id: string | null;
    job_status: string | null;
    candidate_strategy?: string;
    model_portfolio: string[];
    completed_models?: string[];
    failed_models?: Array<Record<string, unknown>>;
    ranked_candidates: Array<Record<string, unknown>>;
    validation_design_id?: string;
    validation_design_version?: string;
    feature_manifest_version?: string;
    split_id?: string;
    tuning_policy?: Record<string, unknown>;
    cv_configuration?: Record<string, unknown>;
    calibration_policy?: Record<string, unknown>;
    runtime_environment?: Record<string, unknown>;
    runtime_ms?: number;
    completed_at?: string;
    model_selection_decision?: Record<string, unknown> | null;
    decision_status?: string;
    stale_reasons?: string[];
  };
  governance: {
    backend_enforced: boolean;
    target_source_excluded: string[];
    automatic_feature_acceptance: boolean;
    automatic_row_removal: boolean;
  };
};

export type EdaCarryForwardContext = {
  documentationStatus: EdaDocumentationState["status"] | "unavailable";
  documentationVersion: string;
  predictorManifestId: string;
  targetSourceExclusions: string[];
  items: PreparationCarryForwardItem[];
  predictorEvidence: Record<
    string,
    {
      iv?: number | null;
      outlierRate?: number | null;
      monotonicity?: string | null;
    }
  >;
  highCorrelationPairs: Array<Record<string, unknown>>;
};

const EMPTY_EDA_CONTEXT: EdaCarryForwardContext = {
  documentationStatus: "unavailable",
  documentationVersion: "",
  predictorManifestId: "",
  targetSourceExclusions: [],
  items: [],
  predictorEvidence: {},
  highCorrelationPairs: [],
};

function asRecord(value: unknown): Record<string, any> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, any>)
    : {};
}

function strings(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => String(item ?? "").trim())
    .filter(Boolean);
}

function decisionStorageKey(
  identity: CanonicalDatasetIdentity,
  stage: PreparationStage,
) {
  return canonicalDatasetStorageKey(
    `atlas:preparation-carry-forward:${stage}`,
    identity,
  );
}

export function loadCarryForwardDispositions(
  identity: CanonicalDatasetIdentity,
  stage: PreparationStage,
) {
  if (typeof localStorage === "undefined") return {} as Record<string, CarryForwardDisposition>;
  try {
    const parsed = JSON.parse(
      localStorage.getItem(decisionStorageKey(identity, stage)) || "{}",
    );
    return asRecord(parsed) as Record<string, CarryForwardDisposition>;
  } catch {
    return {};
  }
}

export function saveCarryForwardDisposition(
  identity: CanonicalDatasetIdentity,
  stage: PreparationStage,
  findingId: string,
  disposition: CarryForwardDisposition,
) {
  if (typeof localStorage === "undefined") return;
  const current = loadCarryForwardDispositions(identity, stage);
  localStorage.setItem(
    decisionStorageKey(identity, stage),
    JSON.stringify({ ...current, [findingId]: disposition }),
  );
}

function destinationMatches(stage: PreparationStage, destination: string) {
  const text = destination.toLowerCase().replace(/[_-]+/g, " ");
  if (!text || text === "downstream" || text === "preprocessing") return true;
  if (stage === "outliers") return /outlier|cap|winsor|special/.test(text);
  if (stage === "missing_values") return /missing|null|imput|special/.test(text);
  if (stage === "validation_design") return /valid|split|fold|test|oot/.test(text);
  if (stage === "model_training") return /train|model|candidate|champion/.test(text);
  return /feature|transform|correl|redundan|multicol|model/.test(text);
}

export async function getEdaCarryForward(
  identity: CanonicalDatasetIdentity,
  stage: PreparationStage,
  signal?: AbortSignal,
): Promise<EdaCarryForwardContext> {
  let state: EdaDocumentationState;
  try {
    state = await getEdaDocumentationState(
      identity.project_id,
      identity,
      signal,
    );
  } catch {
    return EMPTY_EDA_CONTEXT;
  }
  const record = state.current_approved ?? state.draft;
  if (!record) {
    return {
      ...EMPTY_EDA_CONTEXT,
      documentationStatus: state.status,
    };
  }
  try {
    assertExactDatasetIdentity(
      identity,
      {
        project_id: record.project_id,
        dataset_id: record.dataset_id,
        dataset_version_id: (record as Record<string, unknown>)
          .dataset_version_id,
        dataset_version: record.dataset_version,
      },
      "EDA carry-forward documentation",
    );
  } catch {
    return {
      ...EMPTY_EDA_CONTEXT,
      documentationStatus: "stale",
    };
  }
  const findings = asRecord(record.sections?.findings);
  const predictors = asRecord(record.sections?.predictors);
  const relationships = asRecord(record.sections?.relationships);
  const carryForward = Array.isArray(findings.carry_forward)
    ? findings.carry_forward
    : [];
  const dispositions = loadCarryForwardDispositions(identity, stage);
  const items = carryForward
    .map((raw) => asRecord(raw))
    .map((row, index) => {
      const findingId = String(row.finding_id ?? `eda-carry-${index + 1}`);
      return {
        findingId,
        title: String(row.title ?? "Accepted EDA finding"),
        destination: String(row.destination ?? "Downstream preprocessing"),
        recommendation: String(
          row.recommendation ?? "Review this finding before changing the governed preparation plan.",
        ),
        suggestedTransformation: String(row.suggested_transformation ?? ""),
        reviewerRationale: String(row.reviewer_rationale ?? ""),
        sourceStatus: String(row.status ?? "draft_recommendation"),
        disposition: dispositions[findingId] ?? "draft",
      } satisfies PreparationCarryForwardItem;
    })
    .filter((item) => destinationMatches(stage, item.destination));
  const predictorEvidence: EdaCarryForwardContext["predictorEvidence"] = {};
  const mergeMetric = (
    raw: unknown,
    key: "iv" | "outlierRate" | "monotonicity",
    sourceKey: string,
  ) => {
    if (!Array.isArray(raw)) return;
    raw.forEach((item) => {
      const row = asRecord(item);
      const feature = String(row.feature ?? "").trim();
      if (!feature) return;
      const value = row[sourceKey];
      predictorEvidence[feature] = {
        ...(predictorEvidence[feature] ?? {}),
        [key]:
          key === "monotonicity"
            ? value == null
              ? null
              : String(value)
            : typeof value === "number"
              ? value
              : null,
      };
    });
  };
  mergeMetric(predictors.information_value, "iv", "iv");
  mergeMetric(predictors.outliers, "outlierRate", "outlier_rate");
  mergeMetric(predictors.monotonicity, "monotonicity", "monotonicity");

  return {
    documentationStatus: state.status,
    documentationVersion:
      record.documentation_version ?? record.eda_analysis_version ?? "",
    predictorManifestId: record.predictor_manifest_id ?? "",
    targetSourceExclusions: strings(record.target_source_exclusions),
    items,
    predictorEvidence,
    highCorrelationPairs: Array.isArray(relationships.high_correlation_pairs)
      ? relationships.high_correlation_pairs.map(asRecord)
      : [],
  };
}

export async function getPreparationDocumentation(
  identity: CanonicalDatasetIdentity,
  signal?: AbortSignal,
) {
  const query = new URLSearchParams({
    project_id: identity.project_id,
    expected_dataset_id: identity.dataset_id,
    expected_dataset_version_id: identity.dataset_version_id,
  });
  const response = await fetch(
    `${DATASET_API_BASE}/preparation/documentation?${query.toString()}`,
    { credentials: "include", signal },
  );
  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload?.ok) {
    throw new Error(
      payload?.detail ??
        `ATLAS preparation documentation request failed with HTTP ${response.status}.`,
    );
  }
  const state = payload as PreparationDocumentationState;
  assertExactDatasetIdentity(
    identity,
    state,
    "Preparation documentation response",
  );
  return state;
}

export function preparationStatusLabel(status: PreparationDocumentationStatus) {
  if (status === "confirmed") return "Confirmed in MDD";
  if (status === "stale") return "MDD stale";
  return "Draft documentation";
}
