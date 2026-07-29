import {
  getEdaDocumentationState,
  type EdaDocumentationState,
} from "./edaDocumentationApi";
import { DATASET_API_BASE } from "./datasetLibrary";

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

function decisionStorageKey(projectId: string, stage: PreparationStage) {
  return `atlas:preparation-carry-forward:${projectId}:${stage}`;
}

export function loadCarryForwardDispositions(
  projectId: string,
  stage: PreparationStage,
) {
  if (typeof localStorage === "undefined") return {} as Record<string, CarryForwardDisposition>;
  try {
    const parsed = JSON.parse(
      localStorage.getItem(decisionStorageKey(projectId, stage)) || "{}",
    );
    return asRecord(parsed) as Record<string, CarryForwardDisposition>;
  } catch {
    return {};
  }
}

export function saveCarryForwardDisposition(
  projectId: string,
  stage: PreparationStage,
  findingId: string,
  disposition: CarryForwardDisposition,
) {
  if (typeof localStorage === "undefined") return;
  const current = loadCarryForwardDispositions(projectId, stage);
  localStorage.setItem(
    decisionStorageKey(projectId, stage),
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
  projectId: string,
  stage: PreparationStage,
  signal?: AbortSignal,
): Promise<EdaCarryForwardContext> {
  let state: EdaDocumentationState;
  try {
    state = await getEdaDocumentationState(projectId, signal);
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
  const findings = asRecord(record.sections?.findings);
  const predictors = asRecord(record.sections?.predictors);
  const relationships = asRecord(record.sections?.relationships);
  const carryForward = Array.isArray(findings.carry_forward)
    ? findings.carry_forward
    : [];
  const dispositions = loadCarryForwardDispositions(projectId, stage);
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
  projectId: string,
  signal?: AbortSignal,
) {
  const response = await fetch(
    `${DATASET_API_BASE}/preparation/documentation?project_id=${encodeURIComponent(projectId)}`,
    { credentials: "include", signal },
  );
  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload?.ok) {
    throw new Error(
      payload?.detail ??
        `ATLAS preparation documentation request failed with HTTP ${response.status}.`,
    );
  }
  return payload as PreparationDocumentationState;
}

export function preparationStatusLabel(status: PreparationDocumentationStatus) {
  if (status === "confirmed") return "Confirmed in MDD";
  if (status === "stale") return "MDD stale";
  return "Draft documentation";
}
