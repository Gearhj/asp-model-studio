/**
 * Canonical governed identity for the exact immutable Dataset Library version
 * attached to a modeling project.
 *
 * These fields intentionally use the API's unambiguous names. Browser access
 * metadata, profile snapshots, previews, and analysis artifacts are subordinate
 * records and must never be accepted as substitutes for dataset_version_id.
 */
export type CanonicalDatasetIdentity = {
  project_id: string;
  dataset_id: string;
  dataset_version_id: string;
  /** Monotonic revision of the durable project-scoped active selection. */
  activation_revision?: number;
  dataset_version_label?: string;
  dataset_content_hash?: string;
  dataset_schema_hash?: string;
  dataset_source_type?: string;
};

export type CanonicalDatasetIdentityInput = {
  project_id?: unknown;
  dataset_id?: unknown;
  dataset_version_id?: unknown;
  activation_revision?: unknown;
  dataset_version_label?: unknown;
  dataset_content_hash?: unknown;
  dataset_schema_hash?: unknown;
  dataset_source_type?: unknown;
};

export const CANONICAL_DATASET_EVIDENCE_LINEAGE_CONTRACT =
  "canonical_dataset_version" as const;

export type CanonicalEvidenceLineage = CanonicalDatasetIdentity & {
  lineage_contract: typeof CANONICAL_DATASET_EVIDENCE_LINEAGE_CONTRACT;
} & Record<string, unknown>;

export type CanonicalEvidenceEnvelope = CanonicalDatasetIdentity & {
  lineage_contract: typeof CANONICAL_DATASET_EVIDENCE_LINEAGE_CONTRACT;
  lineage: CanonicalEvidenceLineage;
};

export type DatasetIdentityErrorCode =
  | "missing_canonical_identity"
  | "dataset_identity_mismatch"
  | "dataset_activation_mismatch"
  | "dataset_reopen_unresolved"
  | "dataset_reopen_ambiguous";

export class DatasetIdentityError extends Error {
  readonly code: DatasetIdentityErrorCode;

  constructor(code: DatasetIdentityErrorCode, message: string) {
    super(message);
    this.name = "DatasetIdentityError";
    this.code = code;
  }
}

function requiredIdentifier(value: unknown, field: keyof CanonicalDatasetIdentity, context: string): string {
  const identifier = typeof value === "string" ? value.trim() : "";
  if (!identifier) {
    throw new DatasetIdentityError(
      "missing_canonical_identity",
      `${context} is missing the required ${field} field.`,
    );
  }
  return identifier;
}

function optionalIdentifier(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const identifier = value.trim();
  return identifier || undefined;
}

function optionalActivationRevision(value: unknown, context: string): number | undefined {
  if (value == null || value === "") return undefined;
  const revision = typeof value === "number"
    ? value
    : typeof value === "string" && /^\d+$/.test(value.trim())
      ? Number(value.trim())
      : Number.NaN;
  if (!Number.isSafeInteger(revision) || revision < 1) {
    throw new DatasetIdentityError(
      "missing_canonical_identity",
      `${context} contains an invalid activation_revision (durable activation revision).`,
    );
  }
  return revision;
}

/**
 * Validates canonical identity without deriving it from a browser hash,
 * deprecated dataset_version value, Dataset Library ordering, or another
 * subordinate identifier.
 */
export function requireCanonicalDatasetIdentity(
  input: CanonicalDatasetIdentityInput | null | undefined,
  context = "Canonical dataset identity",
): CanonicalDatasetIdentity {
  if (!input || typeof input !== "object") {
    throw new DatasetIdentityError(
      "missing_canonical_identity",
      `${context} is unavailable. Select and activate an exact registered Dataset Library version.`,
    );
  }

  const identity: CanonicalDatasetIdentity = {
    project_id: requiredIdentifier(input.project_id, "project_id", context),
    dataset_id: requiredIdentifier(input.dataset_id, "dataset_id", context),
    dataset_version_id: requiredIdentifier(input.dataset_version_id, "dataset_version_id", context),
  };

  const optionalFields = {
    dataset_version_label: optionalIdentifier(input.dataset_version_label),
    dataset_content_hash: optionalIdentifier(input.dataset_content_hash),
    dataset_schema_hash: optionalIdentifier(input.dataset_schema_hash),
    dataset_source_type: optionalIdentifier(input.dataset_source_type),
  };
  for (const [field, value] of Object.entries(optionalFields)) {
    if (value) {
      (identity as unknown as Record<string, unknown>)[field] = value;
    }
  }
  const activationRevision = optionalActivationRevision(
    input.activation_revision,
    context,
  );
  if (activationRevision != null) identity.activation_revision = activationRevision;
  return identity;
}

/**
 * Confirms that activation returned the exact project, dataset, and immutable
 * version requested by the caller. A contradictory response fails closed.
 */
export function assertExactDatasetActivation(
  expectedInput: CanonicalDatasetIdentityInput,
  activatedInput: CanonicalDatasetIdentityInput,
): CanonicalDatasetIdentity {
  const expected = requireCanonicalDatasetIdentity(expectedInput, "Requested dataset activation identity");
  const activated = requireCanonicalDatasetIdentity(activatedInput, "Authoritative dataset activation response");

  if (
    activated.project_id !== expected.project_id ||
    activated.dataset_id !== expected.dataset_id ||
    activated.dataset_version_id !== expected.dataset_version_id
  ) {
    throw new DatasetIdentityError(
      "dataset_activation_mismatch",
      "Dataset activation returned a different project, dataset, or immutable version than requested.",
    );
  }
  return activated;
}

type LocalDatasetIdentitySource = {
  dataset_id?: unknown;
  dataset_version_id?: unknown;
  dataset_version?: unknown;
  dataset_library?: {
    datasetId?: unknown;
    versionId?: unknown;
  } | null;
};

/**
 * Resolves the exact Dataset Library pair persisted by Data Acquisition.
 *
 * The canonical top-level fields and the exact nested library reference may
 * both be present. When they are, they must agree. The deprecated
 * dataset_version field is comparison-only and can never supply an identity.
 */
export function requireLocalDatasetCanonicalIdentity(
  projectId: string,
  dataset: LocalDatasetIdentitySource | null | undefined,
  context = "Pre-training dataset identity",
): CanonicalDatasetIdentity {
  const topDatasetId = optionalIdentifier(dataset?.dataset_id);
  const topVersionId = optionalIdentifier(dataset?.dataset_version_id);
  const libraryDatasetId = optionalIdentifier(dataset?.dataset_library?.datasetId);
  const libraryVersionId = optionalIdentifier(dataset?.dataset_library?.versionId);
  const legacyVersion = optionalIdentifier(dataset?.dataset_version);

  if (
    (topDatasetId && libraryDatasetId && topDatasetId !== libraryDatasetId) ||
    (topVersionId && libraryVersionId && topVersionId !== libraryVersionId)
  ) {
    throw new DatasetIdentityError(
      "dataset_identity_mismatch",
      `${context} contains conflicting canonical Dataset Library identifiers. Return to Data Acquisition and reactivate the exact version.`,
    );
  }

  const identity = requireCanonicalDatasetIdentity(
    {
      project_id: projectId,
      dataset_id: topDatasetId ?? libraryDatasetId,
      dataset_version_id: topVersionId ?? libraryVersionId,
    },
    context,
  );
  if (legacyVersion && legacyVersion !== identity.dataset_version_id) {
    throw new DatasetIdentityError(
      "dataset_identity_mismatch",
      `${context} contains a legacy dataset_version value that does not mirror dataset_version_id. Return to Data Acquisition and reactivate the exact version.`,
    );
  }
  return identity;
}

/**
 * Verifies that a backend pre-training response is bound to the same exact
 * canonical dataset identity as the active browser workflow.
 */
export function assertExactDatasetIdentity(
  expectedInput: CanonicalDatasetIdentityInput,
  actualInput: CanonicalDatasetIdentityInput & { dataset_version?: unknown },
  context = "Backend pre-training response",
): CanonicalDatasetIdentity {
  const expected = requireCanonicalDatasetIdentity(expectedInput, "Expected dataset identity");
  const actual = requireCanonicalDatasetIdentity(actualInput, context);
  const legacyVersion = optionalIdentifier(actualInput.dataset_version);

  if (
    actual.project_id !== expected.project_id ||
    actual.dataset_id !== expected.dataset_id ||
    actual.dataset_version_id !== expected.dataset_version_id ||
    (legacyVersion && legacyVersion !== actual.dataset_version_id)
  ) {
    throw new DatasetIdentityError(
      "dataset_identity_mismatch",
      `${context} does not match the exact Dataset Library version activated for this project.`,
    );
  }
  return actual;
}

/**
 * Namespaces browser-only workflow preferences by the exact canonical
 * Dataset Library version. Old project-only or global keys are intentionally
 * not consulted by Phase 2A pre-training surfaces.
 */
export function canonicalDatasetStorageKey(
  prefix: string,
  identityInput: CanonicalDatasetIdentityInput,
): string {
  const identity = requireCanonicalDatasetIdentity(
    identityInput,
    "Browser pre-training state identity",
  );
  return [
    prefix,
    encodeURIComponent(identity.project_id),
    encodeURIComponent(identity.dataset_id),
    encodeURIComponent(identity.dataset_version_id),
  ].join(":");
}

/**
 * Builds the authoritative lineage portion of a governed evidence request.
 *
 * Evidence callers send only the canonical snake-case identifiers. The
 * Evidence API derives legacy projectId/datasetIds and lineage camel-case
 * aliases after it has authorized and compared this identity to the active
 * project scope.
 */
export function buildCanonicalEvidenceEnvelope(
  identityInput: CanonicalDatasetIdentityInput,
  lineage: Record<string, unknown> = {},
): CanonicalEvidenceEnvelope {
  const identity = requireCanonicalDatasetIdentity(
    identityInput,
    "Evidence dataset identity",
  );
  return {
    ...identity,
    lineage_contract: CANONICAL_DATASET_EVIDENCE_LINEAGE_CONTRACT,
    lineage: {
      ...lineage,
      ...identity,
      lineage_contract: CANONICAL_DATASET_EVIDENCE_LINEAGE_CONTRACT,
    },
  };
}

export type TargetPersistenceConfiguration = {
  target: string | null;
  selected_columns?: readonly string[];
  event_value?: unknown;
  non_event_value?: unknown;
};

export type TargetPersistencePayload = {
  project_id: string;
  target: string | null;
  selected_columns: string[];
  event_value?: unknown;
  non_event_value?: unknown;
  expected_dataset_id: string;
  expected_dataset_version_id: string;
};

/**
 * Builds a target-only mutation payload. Canonical identity is sent solely as
 * an expectation for backend comparison; it is never presented as mutable
 * dataset state.
 */
export function buildTargetPersistencePayload(
  identityInput: CanonicalDatasetIdentityInput,
  configuration: TargetPersistenceConfiguration,
): TargetPersistencePayload {
  const identity = requireCanonicalDatasetIdentity(identityInput, "Target persistence dataset identity");
  return {
    project_id: identity.project_id,
    target: configuration.target,
    selected_columns: [...(configuration.selected_columns ?? [])],
    event_value: configuration.event_value,
    non_event_value: configuration.non_event_value,
    expected_dataset_id: identity.dataset_id,
    expected_dataset_version_id: identity.dataset_version_id,
  };
}

/**
 * Resolves a reopened workflow only when exactly one backend-authorized
 * candidate matches the persisted canonical triple. No ordering-based
 * substitution is permitted.
 */
export function resolveExactReopenDatasetIdentity(
  persistedInput: CanonicalDatasetIdentityInput,
  authorizedCandidates: readonly CanonicalDatasetIdentityInput[],
): CanonicalDatasetIdentity {
  const persisted = requireCanonicalDatasetIdentity(persistedInput, "Persisted workflow dataset identity");
  const candidates = authorizedCandidates.map((candidate, index) =>
    requireCanonicalDatasetIdentity(candidate, `Authorized dataset identity ${index + 1}`),
  );
  const matches = candidates.filter(
    (candidate) =>
      candidate.project_id === persisted.project_id &&
      candidate.dataset_id === persisted.dataset_id &&
      candidate.dataset_version_id === persisted.dataset_version_id,
  );

  if (matches.length === 0) {
    throw new DatasetIdentityError(
      "dataset_reopen_unresolved",
      "The persisted immutable Dataset Library version is unavailable or unauthorized for this project.",
    );
  }
  if (matches.length !== 1) {
    throw new DatasetIdentityError(
      "dataset_reopen_ambiguous",
      "The persisted dataset identity resolved to multiple authoritative records.",
    );
  }

  return matches.find(() => true) as CanonicalDatasetIdentity;
}
