import { DATASET_API_BASE } from "./datasetLibrary";
import {
  requireCanonicalDatasetIdentity,
  type CanonicalDatasetIdentity,
} from "./datasetIdentity";

const MAX_ANNOTATIONS = 250;
const MAX_SPECIAL_DEFINITIONS = 64;
const SHA256 = /^[0-9a-f]{64}$/;

type UnknownRecord = Record<string, unknown>;

export type BureauMappingState =
  | "exact_verified"
  | "approved_alias"
  | "transformed_or_derived"
  | "probable_review_required"
  | "ambiguous_review_required"
  | "recoding_evidence_required"
  | "unresolved"
  | "out_of_catalog"
  | "rejected";

export type BureauSemanticAuthorityState =
  | "provider_exact"
  | "provider_definition_via_approved_alias"
  | "non_authoritative_derived"
  | "non_authoritative_review_required"
  | "non_authoritative_unresolved"
  | "non_authoritative_stale"
  | "non_authoritative_unentitled"
  | "non_authoritative_mapping";

export type BureauOrdinaryRange = {
  attributeCode: string;
  definitionId: string;
  definitionChecksum: string;
  minimum?: string;
  maximum?: string;
  expression?: string;
};

export type BureauSpecialDefinition = {
  attributeCode: string;
  definitionId: string;
  definitionChecksum: string;
  valueCode: string;
  semanticFamily: string;
  meaning: string;
};

export type BureauCatalogKey = {
  provider: string;
  product: string;
  edition: string;
  dictionaryVersion: string;
};

export type BureauSemanticAnnotation = {
  annotationId: string;
  datasetField: string;
  mappingState: BureauMappingState;
  mappingAccepted: boolean;
  candidateAttributeCode?: string;
  authorityState: BureauSemanticAuthorityState;
  providerAuthoritative: boolean;
  nonAuthoritativeReasons: string[];
  bindingId: string;
  bindingRevision: number;
  bindingRevisionChecksum: string;
  bindingStatus: "active" | "stale";
  bindingCurrent: boolean;
  entitlementVerified: boolean;
  crosswalkId?: string;
  crosswalkRevision?: number;
  catalogVersionId: string;
  catalogKey: BureauCatalogKey;
  catalogChecksum: string;
  description?: string;
  dataType?: string;
  units?: string;
  attributeDefinitionChecksum?: string;
  ordinaryRange?: BureauOrdinaryRange;
  specialDefinitions: BureauSpecialDefinition[];
};

export type BureauSemanticAnnotationSet = {
  projectId: string;
  datasetId: string;
  datasetVersionId: string;
  annotationSetId: string;
  annotationSetChecksum: string;
  schemaChecksum: string;
  bindingId: string;
  bindingRevision: number;
  bindingRevisionChecksum: string;
  crosswalkId?: string;
  crosswalkRevision?: number;
  crosswalkRevisionChecksum?: string;
  catalogVersionId: string;
  catalogKey: BureauCatalogKey;
  catalogChecksum: string;
  acceptedAnnotationCount: number;
  source: "exact_current_binding_and_accepted_crosswalk_decisions";
};

export type BureauSemanticAnnotationContract =
  | {
      state: "available";
      authoritative: true;
      annotationSet: BureauSemanticAnnotationSet;
      annotations: BureauSemanticAnnotation[];
    }
  | {
      state: "unavailable";
      authoritative: false;
      reason: "not_bound" | "not_entitled" | "service_unavailable";
      annotations: [];
    };

export class BureauSemanticAnnotationError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "BureauSemanticAnnotationError";
    this.status = status;
    this.code = code;
  }
}

function record(value: unknown): UnknownRecord {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as UnknownRecord)
    : {};
}

function first(source: UnknownRecord, keys: readonly string[]) {
  for (const key of keys) {
    if (source[key] !== undefined && source[key] !== null) return source[key];
  }
  return undefined;
}

function boundedText(value: unknown, label: string, maximum = 512) {
  const text = typeof value === "string" ? value.trim() : "";
  if (
    !text ||
    text.length > maximum ||
    [...text].some((character) => {
      const code = character.charCodeAt(0);
      return code < 32 || code === 127;
    })
  ) {
    throw new BureauSemanticAnnotationError(
      200,
      "bureau_semantic_annotation_invalid_response",
      `The bounded semantic annotation response is missing ${label}.`,
    );
  }
  return text;
}

function requiredText(source: UnknownRecord, keys: readonly string[], label: string) {
  return boundedText(first(source, keys), label);
}

function optionalText(source: UnknownRecord, keys: readonly string[], maximum = 512) {
  const value = first(source, keys);
  if (value === undefined || value === null || value === "") return undefined;
  return boundedText(value, keys[0] ?? "text", maximum);
}

function checksum(source: UnknownRecord, keys: readonly string[], label: string) {
  const value = requiredText(source, keys, label).toLowerCase();
  if (!SHA256.test(value)) {
    throw new BureauSemanticAnnotationError(
      200,
      "bureau_semantic_annotation_checksum_invalid",
      `The bounded semantic annotation response contains an invalid ${label}.`,
    );
  }
  return value;
}

function optionalChecksum(
  source: UnknownRecord,
  keys: readonly string[],
  label: string,
) {
  const value = optionalText(source, keys, 64);
  if (value === undefined) return undefined;
  const normalized = value.toLowerCase();
  if (!SHA256.test(normalized)) {
    throw new BureauSemanticAnnotationError(
      200,
      "bureau_semantic_annotation_checksum_invalid",
      `The bounded semantic annotation response contains an invalid ${label}.`,
    );
  }
  return normalized;
}

function positiveInteger(source: UnknownRecord, keys: readonly string[], label: string) {
  const value = Number(first(source, keys));
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new BureauSemanticAnnotationError(
      200,
      "bureau_semantic_annotation_revision_invalid",
      `The bounded semantic annotation response contains an invalid ${label}.`,
    );
  }
  return value;
}

function nonNegativeInteger(
  source: UnknownRecord,
  keys: readonly string[],
  label: string,
) {
  const value = Number(first(source, keys));
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new BureauSemanticAnnotationError(
      200,
      "bureau_semantic_annotation_count_invalid",
      `The bounded semantic annotation response contains an invalid ${label}.`,
    );
  }
  return value;
}

function optionalPositiveInteger(source: UnknownRecord, keys: readonly string[]) {
  const raw = first(source, keys);
  if (raw === undefined || raw === null || raw === "") return undefined;
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new BureauSemanticAnnotationError(
      200,
      "bureau_semantic_annotation_revision_invalid",
      "The bounded semantic annotation response contains an invalid optional revision.",
    );
  }
  return value;
}

function requiredBoolean(source: UnknownRecord, keys: readonly string[], label: string) {
  const value = first(source, keys);
  if (typeof value !== "boolean") {
    throw new BureauSemanticAnnotationError(
      200,
      "bureau_semantic_annotation_invalid_response",
      `The bounded semantic annotation response is missing ${label}.`,
    );
  }
  return value;
}

function enumValue<const T extends readonly string[]>(
  source: UnknownRecord,
  keys: readonly string[],
  values: T,
  label: string,
): T[number] {
  const value = requiredText(source, keys, label);
  if (!(values as readonly string[]).includes(value)) {
    throw new BureauSemanticAnnotationError(
      200,
      "bureau_semantic_annotation_state_invalid",
      `The bounded semantic annotation response contains an invalid ${label}.`,
    );
  }
  return value;
}


function normalizeCatalogKey(value: unknown): BureauCatalogKey {
  const source = record(value);
  return {
    provider: requiredText(source, ["provider"], "catalog_key.provider"),
    product: requiredText(source, ["product"], "catalog_key.product"),
    edition: requiredText(source, ["edition"], "catalog_key.edition"),
    dictionaryVersion: requiredText(
      source,
      ["dictionary_version", "version"],
      "catalog_key.dictionary_version",
    ),
  };
}

const MUTATION_FIELDS = [
  "dataset_mutated",
  "target_contract_mutated",
  "treatment_mutated",
  "predictor_authorization_mutated",
  "analysis_partition_mutated",
  "feature_manifest_mutated",
] as const;

function requireNoWorkflowMutation(source: UnknownRecord) {
  for (const mutationField of MUTATION_FIELDS) {
    if (first(source, [mutationField]) !== false) {
      throw new BureauSemanticAnnotationError(
        200,
        "bureau_semantic_annotation_mutation_contract_invalid",
        "The semantic annotation response did not prove that workflow state remains unchanged.",
      );
    }
  }
}

const MAPPING_STATES = [
  "exact_verified",
  "approved_alias",
  "transformed_or_derived",
  "probable_review_required",
  "ambiguous_review_required",
  "recoding_evidence_required",
  "unresolved",
  "out_of_catalog",
  "rejected",
] as const;

const AUTHORITY_STATES = [
  "provider_exact",
  "provider_definition_via_approved_alias",
  "non_authoritative_derived",
  "non_authoritative_review_required",
  "non_authoritative_unresolved",
  "non_authoritative_stale",
  "non_authoritative_unentitled",
  "non_authoritative_mapping",
] as const;

function normalizeRange(value: unknown): BureauOrdinaryRange | undefined {
  if (value === undefined || value === null) return undefined;
  const source = record(value);
  return {
    attributeCode: requiredText(source, ["attribute_code"], "ordinary_range.attribute_code"),
    definitionId: requiredText(source, ["definition_id"], "ordinary_range.definition_id"),
    definitionChecksum: checksum(
      source,
      ["definition_checksum"],
      "ordinary_range.definition_checksum",
    ),
    minimum: optionalText(source, ["ordinary_min"], 128),
    maximum: optionalText(source, ["ordinary_max"], 128),
    expression: optionalText(source, ["range_expression"], 512),
  };
}

function normalizeSpecialDefinition(value: unknown): BureauSpecialDefinition {
  const source = record(value);
  return {
    attributeCode: requiredText(source, ["attribute_code"], "special_definition.attribute_code"),
    definitionId: requiredText(source, ["definition_id"], "special_definition.definition_id"),
    definitionChecksum: checksum(
      source,
      ["definition_checksum"],
      "special_definition.definition_checksum",
    ),
    valueCode: requiredText(source, ["value_code"], "special_definition.value_code"),
    semanticFamily: requiredText(
      source,
      ["semantic_family"],
      "special_definition.semantic_family",
    ),
    meaning: requiredText(source, ["meaning"], "special_definition.meaning"),
  };
}

function normalizeAnnotation(value: unknown): BureauSemanticAnnotation {
  const source = record(value);
  const definitions = first(source, ["special_definitions"]);
  if (!Array.isArray(definitions) || definitions.length > MAX_SPECIAL_DEFINITIONS) {
    throw new BureauSemanticAnnotationError(
      200,
      "bureau_semantic_annotation_bounds_invalid",
      "The bounded semantic annotation response contains an invalid special-definition collection.",
    );
  }
  const reasons = first(source, ["non_authoritative_reasons"]);
  if (!Array.isArray(reasons) || reasons.length > 8) {
    throw new BureauSemanticAnnotationError(
      200,
      "bureau_semantic_annotation_bounds_invalid",
      "The bounded semantic annotation response contains an invalid authority-reason collection.",
    );
  }
  const crosswalkId = optionalText(source, ["crosswalk_id"]);
  const crosswalkRevision = optionalPositiveInteger(source, ["crosswalk_revision"]);
  if (Boolean(crosswalkId) !== Boolean(crosswalkRevision)) {
    throw new BureauSemanticAnnotationError(
      200,
      "bureau_semantic_annotation_crosswalk_identity_invalid",
      "The bounded semantic annotation response contains an incomplete crosswalk identity.",
    );
  }
  const annotation: BureauSemanticAnnotation = {
    annotationId: requiredText(source, ["annotation_id"], "annotation_id"),
    datasetField: requiredText(source, ["dataset_field"], "dataset_field"),
    mappingState: enumValue(source, ["mapping_state"], MAPPING_STATES, "mapping_state"),
    mappingAccepted: requiredBoolean(source, ["mapping_accepted"], "mapping_accepted"),
    candidateAttributeCode: optionalText(source, ["candidate_attribute_code"]),
    authorityState: enumValue(
      source,
      ["authority_state"],
      AUTHORITY_STATES,
      "authority_state",
    ),
    providerAuthoritative: requiredBoolean(
      source,
      ["provider_authoritative"],
      "provider_authoritative",
    ),
    nonAuthoritativeReasons: reasons.map((reason) =>
      boundedText(reason, "non_authoritative_reason", 160),
    ),
    bindingId: requiredText(source, ["binding_id"], "binding_id"),
    bindingRevision: positiveInteger(source, ["binding_revision"], "binding_revision"),
    bindingRevisionChecksum: checksum(
      source,
      ["binding_revision_checksum"],
      "binding_revision_checksum",
    ),
    bindingStatus: enumValue(
      source,
      ["binding_status"],
      ["active", "stale"] as const,
      "binding_status",
    ),
    bindingCurrent: requiredBoolean(source, ["binding_current"], "binding_current"),
    entitlementVerified: requiredBoolean(
      source,
      ["entitlement_verified"],
      "entitlement_verified",
    ),
    crosswalkId,
    crosswalkRevision,
    catalogVersionId: requiredText(source, ["catalog_version_id"], "catalog_version_id"),
    catalogKey: normalizeCatalogKey(first(source, ["catalog_key"])),
    catalogChecksum: checksum(source, ["catalog_checksum"], "catalog_checksum"),
    description: optionalText(source, ["description"], 1_024),
    dataType: optionalText(source, ["data_type"], 128),
    units: optionalText(source, ["units"], 128),
    attributeDefinitionChecksum: optionalChecksum(
      source,
      ["attribute_definition_checksum"],
      "attribute_definition_checksum",
    ),
    ordinaryRange: normalizeRange(first(source, ["ordinary_range"])),
    specialDefinitions: definitions.map(normalizeSpecialDefinition),
  };
  requireNoWorkflowMutation(source);
  const authorityEligible =
    ["exact_verified", "approved_alias"].includes(annotation.mappingState) &&
    annotation.mappingAccepted &&
    Boolean(annotation.candidateAttributeCode) &&
    annotation.bindingStatus === "active" &&
    annotation.bindingCurrent &&
    annotation.entitlementVerified;
  const expectedAuthority =
    annotation.mappingState === "exact_verified"
      ? "provider_exact"
      : annotation.mappingState === "approved_alias"
        ? "provider_definition_via_approved_alias"
        : undefined;
  if (
    annotation.providerAuthoritative !== authorityEligible ||
    (authorityEligible && annotation.authorityState !== expectedAuthority) ||
    (authorityEligible && annotation.nonAuthoritativeReasons.length > 0) ||
    (!authorityEligible && !annotation.authorityState.startsWith("non_authoritative_")) ||
    (!authorityEligible && annotation.nonAuthoritativeReasons.length === 0)
  ) {
    throw new BureauSemanticAnnotationError(
      409,
      "bureau_semantic_annotation_authority_conflict",
      "The semantic annotation authority does not match its accepted mapping, entitlement, and exact binding state.",
    );
  }
  if (
    !annotation.candidateAttributeCode &&
    Boolean(
      annotation.description ||
      annotation.dataType ||
      annotation.units ||
      annotation.attributeDefinitionChecksum ||
      annotation.ordinaryRange ||
      annotation.specialDefinitions.length,
    )
  ) {
    throw new BureauSemanticAnnotationError(
      409,
      "bureau_semantic_annotation_unresolved_semantics_conflict",
      "An unresolved field cannot expose provider semantics.",
    );
  }
  return annotation;
}

function annotationSetRecord(payload: UnknownRecord) {
  const source = record(first(payload, ["annotation_set"]));
  const identity = record(first(source, ["identity"]));
  const binding = record(first(source, ["binding"]));
  const crosswalk = record(first(source, ["crosswalk"]));
  const catalog = record(first(source, ["catalog"]));
  return {
    ...identity,
    ...binding,
    ...crosswalk,
    ...catalog,
    ...source,
  };
}

export function assertBureauSemanticAnnotationContract(
  payload: unknown,
  expectedIdentityInput: CanonicalDatasetIdentity,
): BureauSemanticAnnotationContract {
  const expected = requireCanonicalDatasetIdentity(
    expectedIdentityInput,
    "Bureau semantic annotation identity",
  );
  const envelope = record(payload);
  if (envelope.ok !== true) {
    throw new BureauSemanticAnnotationError(
      200,
      "bureau_semantic_annotation_invalid_response",
      "The backend did not return a valid bounded semantic annotation envelope.",
    );
  }
  const rawAnnotations = first(envelope, ["annotations"]);
  if (!Array.isArray(rawAnnotations) || rawAnnotations.length > MAX_ANNOTATIONS) {
    throw new BureauSemanticAnnotationError(
      200,
      "bureau_semantic_annotation_bounds_invalid",
      "The backend semantic annotation collection exceeded its bounded contract.",
    );
  }
  const source = annotationSetRecord(envelope);
  const annotationSet: BureauSemanticAnnotationSet = {
    projectId: requiredText(source, ["project_id"], "annotation_set.project_id"),
    datasetId: requiredText(source, ["dataset_id"], "annotation_set.dataset_id"),
    datasetVersionId: requiredText(
      source,
      ["dataset_version_id"],
      "annotation_set.dataset_version_id",
    ),
    annotationSetId: requiredText(
      source,
      ["annotation_set_id", "semantic_annotation_set_id"],
      "annotation_set.annotation_set_id",
    ),
    annotationSetChecksum: checksum(
      source,
      ["annotation_set_checksum", "annotations_checksum"],
      "annotation_set.annotation_set_checksum",
    ),
    schemaChecksum: checksum(
      source,
      ["schema_checksum"],
      "annotation_set.schema_checksum",
    ),
    bindingId: requiredText(source, ["binding_id"], "annotation_set.binding_id"),
    bindingRevision: positiveInteger(
      source,
      ["binding_revision", "revision"],
      "annotation_set.binding_revision",
    ),
    bindingRevisionChecksum: checksum(
      source,
      ["binding_revision_checksum", "revision_checksum"],
      "annotation_set.binding_revision_checksum",
    ),
    crosswalkId: optionalText(source, ["crosswalk_id"]),
    crosswalkRevision: optionalPositiveInteger(source, ["crosswalk_revision"]),
    crosswalkRevisionChecksum: optionalText(
      source,
      ["crosswalk_revision_checksum"],
      64,
    ),
    catalogVersionId: requiredText(
      source,
      ["catalog_version_id"],
      "annotation_set.catalog_version_id",
    ),
    catalogKey: normalizeCatalogKey(first(source, ["catalog_key"])),
    catalogChecksum: checksum(
      source,
      ["catalog_checksum"],
      "annotation_set.catalog_checksum",
    ),
    acceptedAnnotationCount: nonNegativeInteger(
      source,
      ["accepted_annotation_count"],
      "annotation_set.accepted_annotation_count",
    ),
    source: enumValue(
      source,
      ["source"],
      ["exact_current_binding_and_accepted_crosswalk_decisions"] as const,
      "annotation_set.source",
    ),
  };
  if (
    annotationSet.projectId !== expected.project_id ||
    annotationSet.datasetId !== expected.dataset_id ||
    annotationSet.datasetVersionId !== expected.dataset_version_id
  ) {
    throw new BureauSemanticAnnotationError(
      409,
      "bureau_semantic_annotation_lineage_stale",
      "The semantic annotations do not match the current exact dataset binding.",
    );
  }
  if (Boolean(annotationSet.crosswalkId) !== Boolean(annotationSet.crosswalkRevision)) {
    throw new BureauSemanticAnnotationError(
      200,
      "bureau_semantic_annotation_crosswalk_identity_invalid",
      "The semantic annotation set contains an incomplete crosswalk identity.",
    );
  }
  if (
    annotationSet.crosswalkRevisionChecksum !== undefined &&
    !SHA256.test(annotationSet.crosswalkRevisionChecksum.toLowerCase())
  ) {
    throw new BureauSemanticAnnotationError(
      200,
      "bureau_semantic_annotation_checksum_invalid",
      "The semantic annotation set contains an invalid crosswalk revision checksum.",
    );
  }
  if (
    Boolean(annotationSet.crosswalkId) !==
    Boolean(annotationSet.crosswalkRevisionChecksum)
  ) {
    throw new BureauSemanticAnnotationError(
      200,
      "bureau_semantic_annotation_crosswalk_identity_invalid",
      "The semantic annotation set contains an incomplete crosswalk checksum identity.",
    );
  }
  requireNoWorkflowMutation(source);
  const annotations = rawAnnotations.map(normalizeAnnotation);
  if (annotationSet.acceptedAnnotationCount !== annotations.length) {
    throw new BureauSemanticAnnotationError(
      409,
      "bureau_semantic_annotation_count_conflict",
      "The semantic annotation count does not match its exact annotation set.",
    );
  }
  const fields = new Set<string>();
  for (const annotation of annotations) {
    if (
      fields.has(annotation.datasetField) ||
      annotation.bindingId !== annotationSet.bindingId ||
      annotation.bindingRevision !== annotationSet.bindingRevision ||
      annotation.bindingRevisionChecksum !== annotationSet.bindingRevisionChecksum ||
      annotation.crosswalkId !== annotationSet.crosswalkId ||
      annotation.crosswalkRevision !== annotationSet.crosswalkRevision ||
      annotation.catalogVersionId !== annotationSet.catalogVersionId ||
      annotation.catalogChecksum !== annotationSet.catalogChecksum ||
      annotation.catalogKey.provider !== annotationSet.catalogKey.provider ||
      annotation.catalogKey.product !== annotationSet.catalogKey.product ||
      annotation.catalogKey.edition !== annotationSet.catalogKey.edition ||
      annotation.catalogKey.dictionaryVersion !==
        annotationSet.catalogKey.dictionaryVersion ||
      annotation.bindingStatus !== "active" ||
      annotation.bindingCurrent !== true ||
      annotation.entitlementVerified !== true ||
      annotation.mappingAccepted !== true
    ) {
      throw new BureauSemanticAnnotationError(
        409,
        "bureau_semantic_annotation_identity_conflict",
        "A semantic annotation contradicts its exact annotation-set identity.",
      );
    }
    fields.add(annotation.datasetField);
  }
  return {
    state: "available",
    authoritative: true,
    annotationSet,
    annotations,
  };
}

function exactAnnotationPath(
  projectId: string,
  identityInput: CanonicalDatasetIdentity,
) {
  const identity = requireCanonicalDatasetIdentity(identityInput);
  const requestedProject = projectId.trim();
  if (!requestedProject || requestedProject !== identity.project_id) {
    throw new BureauSemanticAnnotationError(
      409,
      "bureau_semantic_annotation_project_conflict",
      "The requested project does not match the exact dataset identity.",
    );
  }
  return `/projects/${encodeURIComponent(requestedProject)}/datasets/${encodeURIComponent(
    identity.dataset_id,
  )}/versions/${encodeURIComponent(
    identity.dataset_version_id,
  )}/bureau-metadata/annotations`;
}

export async function fetchBureauSemanticAnnotations(input: {
  projectId: string;
  datasetIdentity: CanonicalDatasetIdentity;
  signal?: AbortSignal;
}): Promise<BureauSemanticAnnotationContract> {
  const path = exactAnnotationPath(input.projectId, input.datasetIdentity);
  let response: Response;
  try {
    response = await fetch(`${DATASET_API_BASE}${path}`, {
      method: "GET",
      credentials: "include",
      headers: { Accept: "application/json" },
      signal: input.signal,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new BureauSemanticAnnotationError(
      0,
      "bureau_semantic_annotation_unavailable",
      "The bounded semantic annotation service is unavailable.",
    );
  }
  if (response.status === 403 || response.status === 404) {
    return {
      state: "unavailable",
      authoritative: false,
      reason: response.status === 403 ? "not_entitled" : "not_bound",
      annotations: [],
    };
  }
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new BureauSemanticAnnotationError(
      response.status,
      "bureau_semantic_annotation_request_failed",
      "The bounded semantic annotation request could not be completed.",
    );
  }
  return assertBureauSemanticAnnotationContract(payload, input.datasetIdentity);
}

export function annotationForDatasetField(
  contract: BureauSemanticAnnotationContract,
  datasetField: string,
) {
  if (contract.state !== "available") return undefined;
  return contract.annotations.find(
    (annotation) => annotation.datasetField === datasetField,
  );
}

export type BureauSemanticAuthorityPresentation = {
  providerAuthoritative: boolean;
  label: string;
  detail: string;
};

/**
 * Re-check the complete authority contract at the presentation boundary.  This
 * deliberately does not infer authority from a catalog code or description.
 * Only an accepted exact/alias mapping on the current entitled binding may be
 * presented as provider-authoritative.
 */
export function isProviderAuthoritativeSemanticAnnotation(
  annotation: BureauSemanticAnnotation,
) {
  const expectedAuthority =
    annotation.mappingState === "exact_verified"
      ? "provider_exact"
      : annotation.mappingState === "approved_alias"
        ? "provider_definition_via_approved_alias"
        : undefined;
  return Boolean(
    expectedAuthority &&
      annotation.mappingAccepted &&
      annotation.candidateAttributeCode &&
      annotation.providerAuthoritative &&
      annotation.authorityState === expectedAuthority &&
      annotation.bindingStatus === "active" &&
      annotation.bindingCurrent &&
      annotation.entitlementVerified &&
      annotation.nonAuthoritativeReasons.length === 0,
  );
}

export function bureauSemanticAuthorityPresentation(
  annotation: BureauSemanticAnnotation,
): BureauSemanticAuthorityPresentation {
  if (isProviderAuthoritativeSemanticAnnotation(annotation)) {
    return {
      providerAuthoritative: true,
      label:
        annotation.mappingState === "approved_alias"
          ? "Provider-authoritative via approved alias"
          : "Provider-authoritative exact match",
      detail:
        "The definition is bound to the current entitled catalog and an explicitly accepted crosswalk decision.",
    };
  }
  const details: Record<BureauMappingState, string> = {
    exact_verified: "The exact mapping did not satisfy the current binding and entitlement authority checks.",
    approved_alias: "The alias mapping did not satisfy the current binding and entitlement authority checks.",
    transformed_or_derived: "Derived or transformed fields are analyst context, not provider definitions.",
    probable_review_required: "This is a probable candidate that still requires governed analyst review.",
    ambiguous_review_required: "Multiple candidates remain plausible, so no provider authority is asserted.",
    recoding_evidence_required: "Recoding or transformation evidence is required before a provider mapping can be accepted.",
    unresolved: "No governed provider mapping has been resolved for this dataset field.",
    out_of_catalog: "The field is outside the bound provider catalog.",
    rejected: "The candidate provider mapping was explicitly rejected.",
  };
  return {
    providerAuthoritative: false,
    label: "Heuristic / non-authoritative",
    detail: details[annotation.mappingState],
  };
}
