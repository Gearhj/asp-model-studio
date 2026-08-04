import { persistenceRequest } from "./serverPersistence";
import type {
  CodeContextFingerprint,
  CodeContextLanguage,
} from "./codeContextSafety";

export const REPRODUCIBILITY_CONTEXT_PENDING_EVENT =
  "atlas-reproducibility-context-pending";
export const REPRODUCIBILITY_CONTEXT_CONFIRMED_EVENT =
  "atlas-reproducibility-context-confirmed";

export function markReproducibilityContextPending() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(REPRODUCIBILITY_CONTEXT_PENDING_EVENT));
  }
}

export function notifyReproducibilityContextConfirmed() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(REPRODUCIBILITY_CONTEXT_CONFIRMED_EVENT));
  }
}

export type ReproducibilityContextState =
  | "identity_pending"
  | "target_pending"
  | "partition_pending"
  | "current";

export type ReproducibilityIdentity = {
  project_id: string;
  dataset_name: string;
  dataset_id: string;
  dataset_version_id: string;
  dataset_version_label: string;
  source_type: string;
  activation_revision: number;
  governed_population_rows: number | null;
  source_columns: number | null;
};

export type ReproducibilityTargetContract = {
  target_contract_id: string;
  target: string;
  event_value: unknown;
  non_event_value: unknown;
};

export type ReproducibilityPredictorAuthorization = {
  predictor_authorization_id: string;
  status: string;
  authorized_predictors: string[];
  selected_predictors: string[];
  excluded_fields: Record<string, string>;
  deterministic_source_exclusions: string[];
  target_source_detection_scope: string;
  funnel: {
    source_column_count: number;
    target_exclusions: Array<{ field: string; reason: string }>;
    candidate_predictor_count: number;
    selected_predictor_count: number;
    authorized_predictor_count: number;
    additional_exclusions: Record<string, string>;
    model_ready_status: "not_established_in_data_acquisition";
  };
};

export type ReproducibilityAnalysisPartition = {
  analysis_partition_id: string;
  revision: number;
  status: string;
  development_share: number;
  holdout_share: number;
  development_rows: number;
  sealed_holdout_rows: number;
  random_seed: number;
  stratification_policy: string;
  stratification_field: string;
  final_holdout_status: string;
  holdout_isolation_status: string;
};

export type DataAcquisitionReproducibilityContext = {
  ok: true;
  state: ReproducibilityContextState;
  project_id: string;
  context_id: string;
  identity: ReproducibilityIdentity | null;
  target_contract: ReproducibilityTargetContract | null;
  predictor_authorization: ReproducibilityPredictorAuthorization | null;
  analysis_partition: ReproducibilityAnalysisPartition | null;
  authority: {
    binding: "exact_registered_version";
    fallback_used: false;
    browser_state_authoritative: false;
    row_data_included: false;
    assignments_included: false;
    target_aggregates_included: false;
    final_holdout_access: "protected_metadata_only";
  };
};

export type CurrentDataAcquisitionReproducibilityContext =
  DataAcquisitionReproducibilityContext & {
    state: "current";
    identity: ReproducibilityIdentity;
    target_contract: ReproducibilityTargetContract;
    predictor_authorization: ReproducibilityPredictorAuthorization;
    analysis_partition: ReproducibilityAnalysisPartition;
  };

export class ReproducibilityContextValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ReproducibilityContextValidationError";
  }
}

export class ReproducibilityContextPendingError extends Error {
  readonly state: Exclude<ReproducibilityContextState, "current">;

  constructor(state: Exclude<ReproducibilityContextState, "current">) {
    super(reproducibilityContextPendingMessage(state));
    this.name = "ReproducibilityContextPendingError";
    this.state = state;
  }
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function requiredString(value: unknown, label: string) {
  const text = typeof value === "string" ? value.trim() : "";
  if (!text) {
    throw new ReproducibilityContextValidationError(
      `The backend reproducibility response is missing ${label}.`,
    );
  }
  return text;
}

function validateAuthority(value: unknown) {
  const authority = record(value);
  if (
    !authority ||
    authority.binding !== "exact_registered_version" ||
    authority.fallback_used !== false ||
    authority.browser_state_authoritative !== false ||
    authority.row_data_included !== false ||
    authority.assignments_included !== false ||
    authority.target_aggregates_included !== false ||
    authority.final_holdout_access !== "protected_metadata_only"
  ) {
    throw new ReproducibilityContextValidationError(
      "The backend did not return the required exact, metadata-only authority contract.",
    );
  }
}

function validatePredictorAuthorization(
  authorization: ReproducibilityPredictorAuthorization,
) {
  requiredString(
    authorization.predictor_authorization_id,
    "predictor_authorization.predictor_authorization_id",
  );
  const funnel = authorization.funnel;
  if (
    !funnel ||
    !Number.isInteger(funnel.source_column_count) ||
    !Number.isInteger(funnel.candidate_predictor_count) ||
    !Number.isInteger(funnel.selected_predictor_count) ||
    !Number.isInteger(funnel.authorized_predictor_count) ||
    funnel.selected_predictor_count !== authorization.selected_predictors.length ||
    funnel.authorized_predictor_count !== authorization.authorized_predictors.length ||
    funnel.model_ready_status !== "not_established_in_data_acquisition"
  ) {
    throw new ReproducibilityContextValidationError(
      "The reproducibility response is missing the backend-authoritative predictor funnel.",
    );
  }
}

function assertRequiredCurrentContract(
  context: DataAcquisitionReproducibilityContext,
): asserts context is CurrentDataAcquisitionReproducibilityContext {
  if (!context.identity || !context.target_contract || !context.predictor_authorization || !context.analysis_partition) {
    throw new ReproducibilityContextValidationError(
      "The current reproducibility response is missing an exact governed contract.",
    );
  }
  requiredString(context.identity.project_id, "identity.project_id");
  requiredString(context.identity.dataset_id, "identity.dataset_id");
  requiredString(context.identity.dataset_version_id, "identity.dataset_version_id");
  requiredString(context.target_contract.target_contract_id, "target_contract.target_contract_id");
  requiredString(context.target_contract.target, "target_contract.target");
  validatePredictorAuthorization(context.predictor_authorization);
  requiredString(
    context.analysis_partition.analysis_partition_id,
    "analysis_partition.analysis_partition_id",
  );
  if (context.identity.activation_revision <= 0 || context.analysis_partition.revision <= 0) {
    throw new ReproducibilityContextValidationError(
      "The current reproducibility response requires positive activation and partition revisions.",
    );
  }
  if (
    context.analysis_partition.status !== "current" ||
    context.analysis_partition.final_holdout_status !== "sealed" ||
    context.analysis_partition.holdout_isolation_status !== "verified"
  ) {
    throw new ReproducibilityContextValidationError(
      "The current reproducibility response is not bound to a verified sealed Analysis Partition.",
    );
  }
}

export function validateDataAcquisitionReproducibilityContext(
  value: unknown,
): DataAcquisitionReproducibilityContext {
  const payload = record(value);
  if (!payload || payload.ok !== true) {
    throw new ReproducibilityContextValidationError(
      "The backend did not return a valid reproducibility response.",
    );
  }
  const states: ReproducibilityContextState[] = [
    "identity_pending",
    "target_pending",
    "partition_pending",
    "current",
  ];
  if (!states.includes(payload.state as ReproducibilityContextState)) {
    throw new ReproducibilityContextValidationError(
      "The backend returned an unknown reproducibility state.",
    );
  }
  requiredString(payload.project_id, "project_id");
  requiredString(payload.context_id, "context_id");
  validateAuthority(payload.authority);

  const context = payload as DataAcquisitionReproducibilityContext;
  if (context.state === "identity_pending") {
    if (context.identity || context.target_contract || context.predictor_authorization || context.analysis_partition) {
      throw new ReproducibilityContextValidationError(
        "Identity-pending context must not publish stale governed metadata.",
      );
    }
  } else if (context.state === "target_pending") {
    if (!context.identity || context.target_contract || context.predictor_authorization || context.analysis_partition) {
      throw new ReproducibilityContextValidationError(
        "Target-pending context must expose only the exact confirmed identity.",
      );
    }
  } else if (context.state === "partition_pending") {
    if (!context.identity || !context.target_contract || !context.predictor_authorization || context.analysis_partition) {
      throw new ReproducibilityContextValidationError(
        "Partition-pending context must expose the exact identity and target authorization only.",
      );
    }
    validatePredictorAuthorization(context.predictor_authorization);
  } else {
    assertRequiredCurrentContract(context);
  }
  return context;
}

export async function fetchDataAcquisitionReproducibilityContext(
  projectId: string,
  signal?: AbortSignal,
) {
  const resolvedProjectId = requiredString(projectId, "request project_id");
  const payload = await persistenceRequest<unknown>(
    `/data/reproducibility-context?project_id=${encodeURIComponent(resolvedProjectId)}`,
    { method: "GET", signal },
  );
  return validateDataAcquisitionReproducibilityContext(payload);
}

export function isCurrentDataAcquisitionReproducibilityContext(
  context: DataAcquisitionReproducibilityContext,
): context is CurrentDataAcquisitionReproducibilityContext {
  return (
    context.state === "current" &&
    Boolean(context.identity) &&
    Boolean(context.target_contract) &&
    Boolean(context.predictor_authorization) &&
    Boolean(context.analysis_partition)
  );
}

export function requireCurrentDataAcquisitionReproducibilityContext(
  context: DataAcquisitionReproducibilityContext,
): CurrentDataAcquisitionReproducibilityContext {
  if (!isCurrentDataAcquisitionReproducibilityContext(context)) {
    throw new ReproducibilityContextPendingError(
      context.state as Exclude<ReproducibilityContextState, "current">,
    );
  }
  assertRequiredCurrentContract(context);
  return context;
}

export function buildConfirmedDataAcquisitionCodeContext(
  input: CurrentDataAcquisitionReproducibilityContext,
  language: CodeContextLanguage,
  workflowPage = "/step01",
): CodeContextFingerprint {
  const context = requireCurrentDataAcquisitionReproducibilityContext(input);
  return {
    schemaVersion: 1,
    datasetId: context.identity.dataset_id,
    datasetVersion: context.identity.dataset_version_id,
    datasetName: context.identity.dataset_name,
    target: context.target_contract.target,
    // The draft identity must change when either predictor authorization or
    // Analysis Partition changes, even if the dataset and target do not.
    predictorManifestId: [
      context.predictor_authorization.predictor_authorization_id,
      context.analysis_partition.analysis_partition_id,
      `revision-${context.analysis_partition.revision}`,
    ].join("@"),
    workflowPage,
    language,
    generatedAt: new Date().toISOString(),
  };
}

export function reproducibilityContextPendingMessage(
  state: Exclude<ReproducibilityContextState, "current">,
) {
  if (state === "identity_pending") {
    return "Confirm one exact registered Dataset Library version before generating code.";
  }
  if (state === "target_pending") {
    return "Confirm the target mapping and predictor authorization before generating code.";
  }
  return "Create and seal the Analysis Partition before publishing current development code.";
}

function safeMetadata(
  input: CurrentDataAcquisitionReproducibilityContext,
) {
  const context = requireCurrentDataAcquisitionReproducibilityContext(input);
  return {
    context_id: context.context_id,
    project_id: context.project_id,
    dataset_name: context.identity.dataset_name,
    dataset_id: context.identity.dataset_id,
    dataset_version_id: context.identity.dataset_version_id,
    activation_revision: context.identity.activation_revision,
    target: context.target_contract.target,
    event_value: context.target_contract.event_value,
    non_event_value: context.target_contract.non_event_value,
    target_contract_id: context.target_contract.target_contract_id,
    predictor_authorization_id:
      context.predictor_authorization.predictor_authorization_id,
    authorized_predictors: [
      ...context.predictor_authorization.authorized_predictors,
    ],
    excluded_fields: {
      ...context.predictor_authorization.excluded_fields,
    },
    deterministic_source_exclusions: [
      ...context.predictor_authorization.deterministic_source_exclusions,
    ],
    target_source_detection_scope:
      context.predictor_authorization.target_source_detection_scope,
    analysis_partition_id:
      context.analysis_partition.analysis_partition_id,
    analysis_partition_revision: context.analysis_partition.revision,
    development_rows: context.analysis_partition.development_rows,
    sealed_holdout_rows: context.analysis_partition.sealed_holdout_rows,
    development_share: context.analysis_partition.development_share,
    sealed_holdout_share: context.analysis_partition.holdout_share,
    random_seed: context.analysis_partition.random_seed,
    stratification_policy:
      context.analysis_partition.stratification_policy,
    stratification_field: context.analysis_partition.stratification_field,
    final_holdout_status: context.analysis_partition.final_holdout_status,
    final_holdout_access: context.authority.final_holdout_access,
  };
}

/** Safely embeds JSON as a Python string literal without interpolating names. */
export function pythonJsonStringLiteral(value: unknown) {
  return JSON.stringify(JSON.stringify(value));
}

/** Safely quotes a SAS character literal; macro triggers remain inert in it. */
export function sasCharacterLiteral(value: unknown) {
  return `'${String(value ?? "").replaceAll("'", "''")}'`;
}

export function buildDataAcquisitionPythonContext(
  input: CurrentDataAcquisitionReproducibilityContext,
) {
  const metadata = safeMetadata(input);
  const encoded = pythonJsonStringLiteral(metadata);
  return `# Backend-confirmed ATLAS Data Acquisition context.
# Metadata only: no local filesystem path is assumed and no rows are loaded here.
# Model development is bound to the development population. The final holdout remains sealed.
import json as _atlas_json

ATLAS_CONTEXT = _atlas_json.loads(${encoded})
PROJECT_ID = ATLAS_CONTEXT["project_id"]
DATASET_NAME = ATLAS_CONTEXT["dataset_name"]
DATASET_ID = ATLAS_CONTEXT["dataset_id"]
DATASET_VERSION_ID = ATLAS_CONTEXT["dataset_version_id"]
TARGET = ATLAS_CONTEXT["target"]
EVENT_VALUE = ATLAS_CONTEXT["event_value"]
NON_EVENT_VALUE = ATLAS_CONTEXT["non_event_value"]
AUTHORIZED_PREDICTORS = list(ATLAS_CONTEXT["authorized_predictors"])
EXCLUDED_FIELDS = dict(ATLAS_CONTEXT["excluded_fields"])
DETERMINISTIC_SOURCE_EXCLUSIONS = list(ATLAS_CONTEXT["deterministic_source_exclusions"])
ANALYSIS_PARTITION_ID = ATLAS_CONTEXT["analysis_partition_id"]
ANALYSIS_PARTITION_REVISION = ATLAS_CONTEXT["analysis_partition_revision"]
DEVELOPMENT_ROWS = ATLAS_CONTEXT["development_rows"]
SEALED_HOLDOUT_ROWS = ATLAS_CONTEXT["sealed_holdout_rows"]

assert ATLAS_CONTEXT["final_holdout_status"] == "sealed"
assert ATLAS_CONTEXT["final_holdout_access"] == "protected_metadata_only"
del _atlas_json
`;
}

export function buildDataAcquisitionSasContext(
  input: CurrentDataAcquisitionReproducibilityContext,
) {
  const metadata = safeMetadata(input);
  const assignments: Array<[string, unknown]> = [
    ["atlas_context_id", metadata.context_id],
    ["atlas_project_id", metadata.project_id],
    ["atlas_dataset_name", metadata.dataset_name],
    ["atlas_dataset_id", metadata.dataset_id],
    ["atlas_dataset_version_id", metadata.dataset_version_id],
    ["atlas_target", metadata.target],
    ["atlas_event_json", JSON.stringify(metadata.event_value)],
    ["atlas_nonevent_json", JSON.stringify(metadata.non_event_value)],
    ["atlas_target_contract_id", metadata.target_contract_id],
    ["atlas_predictor_authorization_id", metadata.predictor_authorization_id],
    ["atlas_analysis_partition_id", metadata.analysis_partition_id],
    ["atlas_analysis_partition_revision", metadata.analysis_partition_revision],
    ["atlas_development_rows", metadata.development_rows],
    ["atlas_sealed_holdout_rows", metadata.sealed_holdout_rows],
    ["atlas_authorized_predictors_json", JSON.stringify(metadata.authorized_predictors)],
    ["atlas_excluded_fields_json", JSON.stringify(metadata.excluded_fields)],
    ["atlas_deterministic_exclusions_json", JSON.stringify(metadata.deterministic_source_exclusions)],
    ["atlas_final_holdout_status", metadata.final_holdout_status],
    ["atlas_final_holdout_access", metadata.final_holdout_access],
  ];
  const statements = assignments.map(
    ([name, value]) =>
      `  call symputx(${sasCharacterLiteral(name)}, ${sasCharacterLiteral(value)}, 'G');`,
  );
  return `/* Backend-confirmed ATLAS Data Acquisition metadata.
   This program does not assume a physical dataset connection and does not load rows.
   Development is the modeling scope; final-holdout information is protected metadata only. */
data _null_;
${statements.join("\n")}
run;
`;
}

export function buildDataAcquisitionMetadataContext(
  input: CurrentDataAcquisitionReproducibilityContext,
) {
  return JSON.stringify(safeMetadata(input), null, 2);
}
