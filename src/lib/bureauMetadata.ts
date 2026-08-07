import { DATASET_API_BASE } from "./datasetLibrary";
import {
  requireCanonicalDatasetIdentity,
  type CanonicalDatasetIdentity,
} from "./datasetIdentity";

type UnknownRecord = Record<string, unknown>;

export type BureauCatalogOption = {
  catalogVersionId: string;
  catalogChecksum: string;
  provider: string;
  product: string;
  edition: string;
  dictionaryVersion: string;
  entitlementState: string;
  integrityState: string;
  lifecycleState: string;
  attributeCount: number;
  specialDefinitionCount: number;
};

export type BureauMetadataBindingIdentity = {
  projectId: string;
  datasetId: string;
  datasetVersionId: string;
  activationRevision?: number;
  schemaChecksum?: string;
  targetContractId?: string;
  predictorAuthorizationId?: string;
  catalogVersionId: string;
  catalogChecksum: string;
  provider: string;
  product: string;
  edition: string;
  dictionaryVersion: string;
};

export type BureauMetadataMappingCounts = {
  authoritative: number;
  reviewRequired: number;
  unresolved: number;
  specialDefinitions: number;
};

export type BureauMetadataBindingSummary = {
  identity: BureauMetadataBindingIdentity;
  bindingId: string;
  bindingRevision: number;
  bindingChecksum: string;
  status: "active" | "stale";
  current: boolean;
  stale: boolean;
  staleReason?: string;
  crosswalkId?: string;
  crosswalkRevision?: number;
  entitlementState: string;
  integrityState: string;
  mappingCounts: BureauMetadataMappingCounts;
  evidenceCount: number;
  evidenceKinds: string[];
  recordedAt?: string;
};

export type BureauMetadataBindingPreview = {
  identity: BureauMetadataBindingIdentity;
  previewChecksum: string;
  expectedRevision: number;
  entitlementState: string;
  integrityState: string;
  mappingCounts: BureauMetadataMappingCounts;
  evidenceCount: number;
  current: boolean;
  stale: boolean;
  datasetMutated: false;
  targetContractMutated: false;
  treatmentMutated: false;
  predictorAuthorizationMutated: false;
  analysisPartitionMutated: false;
  featureManifestMutated: false;
};

export type BureauMetadataRequestErrorKind =
  | "authentication"
  | "entitlement"
  | "not_found"
  | "conflict"
  | "unavailable"
  | "invalid_response"
  | "invalid_request";

export class BureauMetadataRequestError extends Error {
  readonly status: number;
  readonly code: string;
  readonly kind: BureauMetadataRequestErrorKind;
  readonly recovery: string;

  constructor(input: {
    status: number;
    code: string;
    kind: BureauMetadataRequestErrorKind;
    message: string;
    recovery: string;
  }) {
    super(input.message);
    this.name = "BureauMetadataRequestError";
    this.status = input.status;
    this.code = input.code;
    this.kind = input.kind;
    this.recovery = input.recovery;
  }
}

function isRecord(value: unknown): value is UnknownRecord {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function record(value: unknown): UnknownRecord {
  return isRecord(value) ? value : {};
}

function firstValue(source: UnknownRecord, keys: readonly string[]): unknown {
  for (const key of keys) {
    if (source[key] !== undefined && source[key] !== null) return source[key];
  }
  return undefined;
}

function textValue(source: UnknownRecord, keys: readonly string[], fallback = ""): string {
  const value = firstValue(source, keys);
  if (value === undefined || value === null) return fallback;
  return String(value).trim().slice(0, 1_024);
}

function optionalText(source: UnknownRecord, keys: readonly string[]): string | undefined {
  return textValue(source, keys) || undefined;
}

function numberValue(source: UnknownRecord, keys: readonly string[], fallback = 0): number {
  const value = Number(firstValue(source, keys));
  return Number.isFinite(value) && value >= 0 ? value : fallback;
}

function optionalPositiveInteger(
  source: UnknownRecord,
  keys: readonly string[],
): number | undefined {
  const raw = firstValue(source, keys);
  if (raw === undefined || raw === null || raw === "") return undefined;
  const value = Number(raw);
  return Number.isSafeInteger(value) && value >= 1 ? value : undefined;
}

function booleanValue(source: UnknownRecord, keys: readonly string[], fallback: boolean): boolean {
  const value = firstValue(source, keys);
  return typeof value === "boolean" ? value : fallback;
}

function listFrom(payload: unknown, keys: readonly string[]): unknown[] {
  if (Array.isArray(payload)) return payload;
  const source = record(payload);
  for (const key of keys) {
    if (Array.isArray(source[key])) return source[key] as unknown[];
  }
  return [];
}

function normalizedChecksum(value: string): string {
  const checksum = value.trim().toLowerCase();
  return /^[0-9a-f]{64}$/.test(checksum) ? checksum : "";
}

function requestError(status: number, payload: unknown): BureauMetadataRequestError {
  const source = record(payload);
  const detail = record(source.detail);
  const code = textValue(
    detail,
    ["code"],
    textValue(source, ["code"], "bureau_metadata_request_failed"),
  );
  if (status === 401) {
    return new BureauMetadataRequestError({
      status,
      code,
      kind: "authentication",
      message: "Your ATLAS session is not authenticated for bureau metadata binding.",
      recovery: "Sign in again, then reopen this exact project and dataset version.",
    });
  }
  if (status === 403) {
    return new BureauMetadataRequestError({
      status,
      code,
      kind: "entitlement",
      message: "Bureau metadata is unavailable for this project and session.",
      recovery: "Ask an ATLAS administrator to verify project access and an exact catalog entitlement.",
    });
  }
  if (status === 404) {
    return new BureauMetadataRequestError({
      status,
      code,
      kind: "not_found",
      message: "The exact bureau metadata binding or catalog version was not found.",
      recovery: "Review the exact dataset and catalog version. ATLAS did not substitute another version.",
    });
  }
  if (status === 409 || status === 412) {
    return new BureauMetadataRequestError({
      status,
      code,
      kind: "conflict",
      message: "The governed identity or binding revision changed before this action completed.",
      recovery: "Refresh the binding summary, then prepare a new preview against the current exact identity.",
    });
  }
  return new BureauMetadataRequestError({
    status,
    code,
    kind: "unavailable",
    message:
      status >= 500
        ? "The bureau metadata binding service is temporarily unavailable."
        : "ATLAS could not complete the bureau metadata binding request.",
    recovery:
      status >= 500
        ? "Retry after the service is available. No binding or workflow state was changed."
        : "Review the exact selection and retry. No alternate catalog version was selected.",
  });
}

async function bureauMetadataFetch(
  path: string,
  init?: RequestInit,
  options: { allowNotFound?: boolean; allowPartial?: boolean } = {},
): Promise<unknown | null> {
  let response: Response;
  try {
    response = await fetch(`${DATASET_API_BASE}${path}`, {
      credentials: "include",
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...(init?.headers ?? {}),
      },
    });
  } catch {
    throw new BureauMetadataRequestError({
      status: 0,
      code: "bureau_metadata_network_unavailable",
      kind: "unavailable",
      message: "The bureau metadata binding service could not be reached.",
      recovery: "Retry when the ATLAS backend is available. No binding or workflow state was changed.",
    });
  }
  const payload = await response.json().catch(() => null);
  if (response.status === 404 && options.allowNotFound) return null;
  const structuredPartial =
    options.allowPartial === true &&
    isRecord(payload) &&
    payload.ok === false &&
    payload.partial_metadata_state === true;
  if ((!response.ok || (isRecord(payload) && payload.ok === false)) && !structuredPartial) {
    throw requestError(response.status, payload);
  }
  if (!payload) {
    throw new BureauMetadataRequestError({
      status: response.status,
      code: "bureau_metadata_empty_response",
      kind: "invalid_response",
      message: "ATLAS returned an empty bureau metadata response.",
      recovery: "Refresh this exact binding summary before continuing.",
    });
  }
  return payload;
}

function exactBindingPath(projectId: string, identityInput: CanonicalDatasetIdentity): string {
  const identity = requireCanonicalDatasetIdentity(
    identityInput,
    "Bureau metadata binding identity",
  );
  const exactProjectId = projectId.trim();
  if (!exactProjectId || exactProjectId !== identity.project_id) {
    throw new BureauMetadataRequestError({
      status: 409,
      code: "bureau_metadata_project_identity_conflict",
      kind: "invalid_request",
      message: "The active project does not match the exact dataset identity.",
      recovery: "Reopen the intended project and exact Dataset Library version before binding metadata.",
    });
  }
  return `/projects/${encodeURIComponent(exactProjectId)}/datasets/${encodeURIComponent(
    identity.dataset_id,
  )}/versions/${encodeURIComponent(identity.dataset_version_id)}/bureau-metadata/binding`;
}

function normalizeCatalogOption(input: unknown): BureauCatalogOption | null {
  const source = record(input);
  const versionId = textValue(source, [
    "catalog_version_id",
    "catalogVersionId",
    "version_id",
    "versionId",
  ]);
  const checksum = normalizedChecksum(
    textValue(source, [
      "normalized_catalog_checksum",
      "normalizedCatalogChecksum",
      "catalog_checksum",
      "catalogChecksum",
    ]),
  );
  if (!versionId || !checksum) return null;
  return {
    catalogVersionId: versionId,
    catalogChecksum: checksum,
    provider: textValue(source, ["provider_name", "providerName", "provider"], "Provider not reported"),
    product: textValue(source, ["product_name", "productName", "product"], "Product not reported"),
    edition: textValue(source, ["edition"], "Edition not reported"),
    dictionaryVersion: textValue(
      source,
      ["source_release_version", "sourceReleaseVersion", "dictionary_version", "dictionaryVersion"],
      "Version not reported",
    ),
    entitlementState: textValue(
      source,
      ["entitlement_status", "entitlementStatus", "entitlement_state", "entitlementState"],
      "authorized",
    ),
    integrityState: textValue(source, ["integrity_status", "integrityStatus"], "unknown"),
    lifecycleState: textValue(
      source,
      ["retired_status", "retiredStatus", "lifecycle_status", "lifecycleStatus"],
      "unknown",
    ),
    attributeCount: numberValue(source, ["record_count", "recordCount", "attribute_count", "attributeCount"]),
    specialDefinitionCount: numberValue(source, [
      "special_value_definition_count",
      "specialValueDefinitionCount",
      "special_definition_count",
      "specialDefinitionCount",
    ]),
  };
}

function normalizeMappingCounts(...sources: UnknownRecord[]): BureauMetadataMappingCounts {
  const candidates = sources.flatMap((source) => {
    const nested = record(firstValue(source, ["mapping_counts", "mappingCounts", "counts"]));
    return [nested, source];
  });
  function find(keys: readonly string[]): number {
    for (const source of candidates) {
      const raw = firstValue(source, keys);
      if (raw !== undefined && raw !== null) return numberValue(source, keys);
    }
    return 0;
  }
  return {
    authoritative: find([
      "authoritative_mapping_count",
      "authoritativeMappingCount",
      "authoritative_count",
      "authoritativeCount",
    ]),
    reviewRequired: find([
      "review_required_count",
      "reviewRequiredCount",
      "review_count",
      "reviewCount",
    ]),
    unresolved: find(["unresolved_count", "unresolvedCount"]),
    specialDefinitions: find([
      "special_definition_count",
      "specialDefinitionCount",
      "special_value_definition_count",
      "specialValueDefinitionCount",
    ]),
  };
}

function normalizeIdentity(input: unknown): BureauMetadataBindingIdentity {
  const source = record(input);
  const key = record(firstValue(source, ["catalog_key", "catalogKey"]));
  const identity: BureauMetadataBindingIdentity = {
    projectId: textValue(source, ["project_id", "projectId"]),
    datasetId: textValue(source, ["dataset_id", "datasetId"]),
    datasetVersionId: textValue(source, ["dataset_version_id", "datasetVersionId"]),
    activationRevision: optionalPositiveInteger(source, ["activation_revision", "activationRevision"]),
    schemaChecksum: optionalText(source, ["schema_checksum", "schemaChecksum"]),
    targetContractId: optionalText(source, ["target_contract_id", "targetContractId"]),
    predictorAuthorizationId: optionalText(source, [
      "predictor_authorization_id",
      "predictorAuthorizationId",
    ]),
    catalogVersionId: textValue(source, ["catalog_version_id", "catalogVersionId"]),
    catalogChecksum: normalizedChecksum(
      textValue(source, ["catalog_checksum", "catalogChecksum"]),
    ),
    provider: textValue(source, ["provider"], textValue(key, ["provider"], "Provider not reported")),
    product: textValue(source, ["product"], textValue(key, ["product"], "Product not reported")),
    edition: textValue(source, ["edition"], textValue(key, ["edition"], "Edition not reported")),
    dictionaryVersion: textValue(
      source,
      ["dictionary_version", "dictionaryVersion"],
      textValue(key, ["dictionary_version", "dictionaryVersion"], "Version not reported"),
    ),
  };
  if (
    !identity.projectId ||
    !identity.datasetId ||
    !identity.datasetVersionId ||
    !identity.catalogVersionId ||
    !identity.catalogChecksum
  ) {
    throw new BureauMetadataRequestError({
      status: 200,
      code: "bureau_metadata_identity_missing",
      kind: "invalid_response",
      message: "The bureau metadata response did not include its complete exact identity.",
      recovery: "Refresh this project and exact dataset version before continuing.",
    });
  }
  return identity;
}

function assertExactResponseIdentity(
  expected: CanonicalDatasetIdentity,
  actual: BureauMetadataBindingIdentity,
  expectedCatalogVersionId?: string,
): void {
  const activationContradictory =
    expected.activation_revision !== undefined &&
    actual.activationRevision !== undefined &&
    expected.activation_revision !== actual.activationRevision;
  if (
    expected.project_id !== actual.projectId ||
    expected.dataset_id !== actual.datasetId ||
    expected.dataset_version_id !== actual.datasetVersionId ||
    activationContradictory ||
    (expectedCatalogVersionId && expectedCatalogVersionId !== actual.catalogVersionId)
  ) {
    throw new BureauMetadataRequestError({
      status: 409,
      code: "bureau_metadata_response_identity_conflict",
      kind: "conflict",
      message: "The bureau metadata response does not match the requested exact identity.",
      recovery: "Do not confirm this preview. Refresh the exact project and dataset version.",
    });
  }
}

function normalizeBinding(
  payload: unknown,
  expectedIdentity: CanonicalDatasetIdentity,
): BureauMetadataBindingSummary {
  const envelope = record(payload);
  const binding = record(firstValue(envelope, ["binding", "record", "result"]) ?? envelope);
  const summary = record(firstValue(envelope, ["summary", "binding_summary", "bindingSummary"]));
  const identity = normalizeIdentity(firstValue(binding, ["identity"]) ?? firstValue(summary, ["identity"]));
  assertExactResponseIdentity(expectedIdentity, identity);
  const statusValue = textValue(binding, ["status"], "active").toLowerCase();
  const status: "active" | "stale" = statusValue === "stale" ? "stale" : "active";
  const evidence = listFrom(binding, ["evidence"]);
  const evidenceKinds = Array.from(
    new Set(
      evidence
        .map((item) => textValue(record(item), ["evidence_kind", "evidenceKind", "kind"]))
        .filter(Boolean),
    ),
  ).slice(0, 12);
  const stale = booleanValue(summary, ["stale", "is_stale", "isStale"], status === "stale");
  return {
    identity,
    bindingId: textValue(binding, ["binding_id", "bindingId"]),
    bindingRevision: numberValue(binding, ["revision", "binding_revision", "bindingRevision"]),
    bindingChecksum: textValue(binding, ["revision_checksum", "revisionChecksum", "binding_checksum", "bindingChecksum"]),
    status,
    current: booleanValue(summary, ["current", "is_current", "isCurrent"], !stale && status === "active"),
    stale,
    staleReason: optionalText(binding, ["stale_reason", "staleReason"]),
    crosswalkId: optionalText(binding, ["crosswalk_id", "crosswalkId"]),
    crosswalkRevision: optionalPositiveInteger(binding, ["crosswalk_revision", "crosswalkRevision"]),
    entitlementState: textValue(
      summary,
      ["entitlement_state", "entitlementState", "entitlement_status", "entitlementStatus"],
      "authorized",
    ),
    integrityState: textValue(
      summary,
      ["integrity_state", "integrityState", "integrity_status", "integrityStatus"],
      "verified",
    ),
    mappingCounts: normalizeMappingCounts(summary, binding),
    evidenceCount: numberValue(
      summary,
      ["evidence_count", "evidenceCount"],
      evidence.length,
    ),
    evidenceKinds,
    recordedAt: optionalText(binding, ["server_recorded_at", "serverRecordedAt", "recorded_at", "recordedAt"]),
  };
}

function normalizePreview(
  payload: unknown,
  expectedIdentity: CanonicalDatasetIdentity,
  expectedCatalog: BureauCatalogOption,
  expectedRevision: number,
): BureauMetadataBindingPreview {
  const envelope = record(payload);
  const preview = record(firstValue(envelope, ["preview", "result"]) ?? envelope);
  const summary = record(firstValue(envelope, ["summary", "preview_summary", "previewSummary"]));
  const identity = normalizeIdentity(firstValue(preview, ["identity"]));
  assertExactResponseIdentity(expectedIdentity, identity, expectedCatalog.catalogVersionId);
  if (identity.catalogChecksum !== expectedCatalog.catalogChecksum) {
    throw new BureauMetadataRequestError({
      status: 409,
      code: "bureau_metadata_catalog_checksum_conflict",
      kind: "conflict",
      message: "The preview catalog checksum does not match the exact selected catalog version.",
      recovery: "Do not confirm this preview. Refresh the entitled catalog inventory.",
    });
  }
  const impact = record(firstValue(preview, ["impact", "mutation_impact", "mutationImpact"]));
  const previewChecksum = normalizedChecksum(
    textValue(preview, ["preview_checksum", "previewChecksum"]),
  );
  if (!previewChecksum) {
    throw new BureauMetadataRequestError({
      status: 200,
      code: "bureau_metadata_preview_checksum_missing",
      kind: "invalid_response",
      message: "The binding preview did not return a verifiable preview checksum.",
      recovery: "Prepare a new preview before confirmation.",
    });
  }
  const mutationFlags = {
    dataset: booleanValue(impact, ["dataset_mutated", "datasetMutated"], false),
    targetContract: booleanValue(
      impact,
      ["target_contract_mutated", "targetContractMutated"],
      false,
    ),
    treatment: booleanValue(impact, ["treatment_mutated", "treatmentMutated"], false),
    predictorAuthorization: booleanValue(
      impact,
      ["predictor_authorization_mutated", "predictorAuthorizationMutated"],
      false,
    ),
    analysisPartition: booleanValue(
      impact,
      ["analysis_partition_mutated", "analysisPartitionMutated"],
      false,
    ),
    featureManifest: booleanValue(
      impact,
      ["feature_manifest_mutated", "featureManifestMutated"],
      false,
    ),
  };
  if (Object.values(mutationFlags).some(Boolean)) {
    throw new BureauMetadataRequestError({
      status: 409,
      code: "bureau_metadata_preview_mutation_conflict",
      kind: "conflict",
      message: "The binding preview reported an impermissible workflow mutation.",
      recovery: "Do not confirm this preview. Binding metadata must remain nonmutating.",
    });
  }
  return {
    identity,
    previewChecksum,
    expectedRevision: numberValue(
      preview,
      ["expected_revision", "expectedRevision"],
      expectedRevision,
    ),
    entitlementState: textValue(
      preview,
      ["entitlement_state", "entitlementState"],
      textValue(summary, ["entitlement_state", "entitlementState"], "authorized"),
    ),
    integrityState: textValue(
      preview,
      ["integrity_state", "integrityState"],
      textValue(summary, ["integrity_state", "integrityState"], "verified"),
    ),
    mappingCounts: normalizeMappingCounts(preview, summary),
    evidenceCount: numberValue(preview, ["evidence_count", "evidenceCount"], numberValue(summary, ["evidence_count", "evidenceCount"])),
    current: booleanValue(preview, ["current", "is_current", "isCurrent"], true),
    stale: booleanValue(preview, ["stale", "is_stale", "isStale"], false),
    datasetMutated: false,
    targetContractMutated: false,
    treatmentMutated: false,
    predictorAuthorizationMutated: false,
    analysisPartitionMutated: false,
    featureManifestMutated: false,
  };
}

export async function listEntitledBureauCatalogs(options: { signal?: AbortSignal } = {}): Promise<BureauCatalogOption[]> {
  const payload = await bureauMetadataFetch("/bureau-catalogs?offset=0&limit=50", {
    signal: options.signal,
  });
  return listFrom(payload, ["versions", "catalogs", "items"])
    .map(normalizeCatalogOption)
    .filter((item): item is BureauCatalogOption => item !== null);
}

export async function getBureauMetadataBinding(input: {
  projectId: string;
  datasetIdentity: CanonicalDatasetIdentity;
  signal?: AbortSignal;
}): Promise<BureauMetadataBindingSummary | null> {
  const identity = requireCanonicalDatasetIdentity(input.datasetIdentity);
  const payload = await bureauMetadataFetch(
    exactBindingPath(input.projectId, identity),
    { signal: input.signal },
    { allowNotFound: true },
  );
  return payload ? normalizeBinding(payload, identity) : null;
}

export async function previewBureauMetadataBinding(input: {
  projectId: string;
  datasetIdentity: CanonicalDatasetIdentity;
  catalog: BureauCatalogOption;
  expectedRevision: number;
  signal?: AbortSignal;
}): Promise<BureauMetadataBindingPreview> {
  const identity = requireCanonicalDatasetIdentity(input.datasetIdentity);
  const payload = await bureauMetadataFetch(
    `${exactBindingPath(input.projectId, identity)}/preview`,
    {
      method: "POST",
      signal: input.signal,
      body: JSON.stringify({
        catalog_version_id: input.catalog.catalogVersionId,
        catalog_checksum: input.catalog.catalogChecksum,
      }),
    },
  );
  return normalizePreview(
    payload,
    identity,
    input.catalog,
    Math.max(0, Math.floor(input.expectedRevision)),
  );
}

export async function confirmBureauMetadataBinding(input: {
  projectId: string;
  datasetIdentity: CanonicalDatasetIdentity;
  catalog: BureauCatalogOption;
  preview: BureauMetadataBindingPreview;
  analystRationale: string;
  signal?: AbortSignal;
}): Promise<BureauMetadataBindingSummary> {
  const identity = requireCanonicalDatasetIdentity(input.datasetIdentity);
  assertExactResponseIdentity(identity, input.preview.identity, input.catalog.catalogVersionId);
  const analystRationale = input.analystRationale.trim().slice(0, 1_000);
  if (analystRationale.length < 8) {
    throw new BureauMetadataRequestError({
      status: 400,
      code: "bureau_metadata_rationale_required",
      kind: "invalid_request",
      message: "A concise analyst rationale is required to confirm this exact binding.",
      recovery: "Enter at least 8 characters explaining why this catalog version applies.",
    });
  }
  const payload = await bureauMetadataFetch(
    `${exactBindingPath(input.projectId, identity)}/confirm`,
    {
      method: "POST",
      signal: input.signal,
      body: JSON.stringify({
        catalog_version_id: input.catalog.catalogVersionId,
        catalog_checksum: input.catalog.catalogChecksum,
        expected_revision: input.preview.expectedRevision,
        preview_checksum: input.preview.previewChecksum,
        analyst_rationale: analystRationale,
      }),
    },
  );
  const binding = normalizeBinding(payload, identity);
  if (
    binding.identity.catalogVersionId !== input.catalog.catalogVersionId ||
    binding.identity.catalogChecksum !== input.catalog.catalogChecksum
  ) {
    throw new BureauMetadataRequestError({
      status: 409,
      code: "bureau_metadata_confirmed_catalog_conflict",
      kind: "conflict",
      message: "The confirmed binding does not match the exact previewed catalog version.",
      recovery: "Stop and refresh the binding summary before taking another action.",
    });
  }
  return binding;
}

export const BUREAU_CROSSWALK_STATES = [
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

export type BureauCrosswalkState = (typeof BUREAU_CROSSWALK_STATES)[number];

export type BureauCrosswalkEvidenceReference = {
  evidenceId: string;
  evidenceKind: string;
  authorityId: string;
  checksum: string;
};

export type BureauCrosswalkCandidate = {
  datasetField: string;
  candidateAttributeCode?: string;
  matchStatus: string;
  confidence: number;
  alternatives: string[];
  concerns: string[];
  institutionalAliasReference?: string;
};

export type BureauCrosswalkDecision = {
  datasetField: string;
  mappingState: BureauCrosswalkState;
  candidateAttributeCode?: string;
  alternativeAttributeCodes: string[];
  sourceAttributeCodes: string[];
  rationale?: string;
  aliasAuthorityId?: string;
  institutionalAliasReference?: string;
  transformationReferenceId?: string;
  transformationRule?: string;
  transformationOrRecodingConcerns: string[];
  dataType?: string;
  units?: string;
  sourceSystem?: string;
  timing?: string;
  specialValueHandling?: string;
  valueRangeReconciliation?: string;
  specialValueReconciliation?: string;
  analystConfirmed: boolean;
  evidence: BureauCrosswalkEvidenceReference[];
};

export type BureauCrosswalkStateCounts = Record<BureauCrosswalkState, number>;

export type BureauCrosswalkPreview = {
  sourceCrosswalkId: string;
  sourceCrosswalkChecksum: string;
  persisted: false;
  candidates: BureauCrosswalkCandidate[];
  decisions: BureauCrosswalkDecision[];
  stateCounts: BureauCrosswalkStateCounts;
  authorizedPredictorCount: number;
  candidateCount: number;
};

export type BureauCrosswalkGovernance = {
  governanceId: string;
  revision: number;
  revisionChecksum: string;
  lifecycleState: "draft" | "review_required" | "confirmed";
  sourceCrosswalkId: string;
  sourceCrosswalkChecksum: string;
  decisions: BureauCrosswalkDecision[];
  stateCounts: BureauCrosswalkStateCounts;
  recordedAt?: string;
  bindingRevision?: number;
  bindingLinked: boolean;
};

export type BureauCrosswalkHistory = {
  returned: number;
  totalRevisions: number;
  revisions: BureauCrosswalkGovernance[];
};

export type BureauCrosswalkDecisionInput = {
  datasetField: string;
  mappingState: BureauCrosswalkState;
  candidateAttributeCode?: string;
  alternativeAttributeCodes?: string[];
  sourceAttributeCodes?: string[];
  rationale?: string;
  aliasAuthorityId?: string;
  institutionalAliasReference?: string;
  transformationReferenceId?: string;
  transformationRule?: string;
  transformationOrRecodingConcerns?: string[];
  dataType?: string;
  units?: string;
  sourceSystem?: string;
  timing?: string;
  specialValueHandling?: string;
  valueRangeReconciliation?: string;
  specialValueReconciliation?: string;
};

export type BureauCrosswalkDecisionResult = {
  partialMetadataState: boolean;
  governancePersisted: boolean;
  bindingLinked: boolean;
  governance?: BureauCrosswalkGovernance;
  governanceId?: string;
  crosswalkRevision?: number;
  crosswalkRevisionChecksum?: string;
  errorMessage?: string;
};

const CROSSWALK_STATE_SET = new Set<string>(BUREAU_CROSSWALK_STATES);

function emptyCrosswalkCounts(): BureauCrosswalkStateCounts {
  return {
    exact_verified: 0,
    approved_alias: 0,
    transformed_or_derived: 0,
    probable_review_required: 0,
    ambiguous_review_required: 0,
    recoding_evidence_required: 0,
    unresolved: 0,
    out_of_catalog: 0,
    rejected: 0,
  };
}

function normalizeCrosswalkState(value: unknown): BureauCrosswalkState {
  const state = String(value ?? "").trim();
  return CROSSWALK_STATE_SET.has(state)
    ? (state as BureauCrosswalkState)
    : "unresolved";
}

function boundedTextList(value: unknown, limit: number): string[] {
  if (!Array.isArray(value)) return [];
  return Array.from(
    new Set(value.map((item) => String(item ?? "").trim()).filter(Boolean)),
  ).slice(0, limit);
}

function normalizeCrosswalkEvidence(input: unknown): BureauCrosswalkEvidenceReference | null {
  const source = record(input);
  const evidenceId = textValue(source, ["evidence_id", "evidenceId"]);
  const checksum = normalizedChecksum(textValue(source, ["checksum"]));
  if (!evidenceId || !checksum) return null;
  return {
    evidenceId,
    evidenceKind: textValue(source, ["evidence_kind", "evidenceKind"], "bounded_reference"),
    authorityId: textValue(source, ["authority_id", "authorityId"], "authority not reported"),
    checksum,
  };
}

function normalizeCrosswalkDecision(input: unknown): BureauCrosswalkDecision | null {
  const source = record(input);
  const datasetField = textValue(source, ["dataset_field", "datasetField"]);
  if (!datasetField) return null;
  return {
    datasetField,
    mappingState: normalizeCrosswalkState(firstValue(source, ["mapping_state", "mappingState"])),
    candidateAttributeCode: optionalText(source, ["candidate_attribute_code", "candidateAttributeCode"]),
    alternativeAttributeCodes: boundedTextList(
      firstValue(source, ["alternative_attribute_codes", "alternativeAttributeCodes"]),
      32,
    ),
    sourceAttributeCodes: boundedTextList(
      firstValue(source, ["source_attribute_codes", "sourceAttributeCodes"]),
      32,
    ),
    rationale: optionalText(source, ["rationale"]),
    aliasAuthorityId: optionalText(source, ["alias_authority_id", "aliasAuthorityId"]),
    institutionalAliasReference: optionalText(source, ["institutional_alias_reference", "institutionalAliasReference"]),
    transformationReferenceId: optionalText(source, ["transformation_reference_id", "transformationReferenceId"]),
    transformationRule: optionalText(source, ["transformation_rule", "transformationRule"]),
    transformationOrRecodingConcerns: boundedTextList(
      firstValue(source, ["transformation_or_recoding_concerns", "transformationOrRecodingConcerns"]),
      16,
    ),
    dataType: optionalText(source, ["data_type", "dataType"]),
    units: optionalText(source, ["units"]),
    sourceSystem: optionalText(source, ["source_system", "sourceSystem"]),
    timing: optionalText(source, ["timing"]),
    specialValueHandling: optionalText(source, ["special_value_handling", "specialValueHandling"]),
    valueRangeReconciliation: optionalText(source, ["value_range_reconciliation", "valueRangeReconciliation"]),
    specialValueReconciliation: optionalText(source, ["special_value_reconciliation", "specialValueReconciliation"]),
    analystConfirmed: booleanValue(source, ["analyst_confirmed", "analystConfirmed"], false),
    evidence: listFrom(source, ["evidence"])
      .map(normalizeCrosswalkEvidence)
      .filter((item): item is BureauCrosswalkEvidenceReference => item !== null)
      .slice(0, 32),
  };
}

function normalizeCrosswalkCandidate(input: unknown): BureauCrosswalkCandidate | null {
  const source = record(input);
  const datasetField = textValue(source, ["dataset_field", "datasetField"]);
  if (!datasetField) return null;
  const confidenceRaw = Number(firstValue(source, ["confidence"]));
  return {
    datasetField,
    candidateAttributeCode: optionalText(source, ["candidate_attribute_code", "candidateAttributeCode"]),
    matchStatus: textValue(source, ["match_status", "matchStatus"], "no_supported_match"),
    confidence: Number.isFinite(confidenceRaw) ? Math.max(0, Math.min(1, confidenceRaw)) : 0,
    alternatives: boundedTextList(firstValue(source, ["ambiguity", "alternatives"]), 32),
    concerns: boundedTextList(
      firstValue(source, ["transformation_or_recoding_concerns", "transformationOrRecodingConcerns"]),
      16,
    ),
    institutionalAliasReference: optionalText(source, ["institutional_alias_reference", "institutionalAliasReference"]),
  };
}

function crosswalkCounts(decisions: readonly BureauCrosswalkDecision[]): BureauCrosswalkStateCounts {
  const counts = emptyCrosswalkCounts();
  for (const decision of decisions) counts[decision.mappingState] += 1;
  return counts;
}

function assertCrosswalkNonmutation(payload: unknown): void {
  const envelope = record(payload);
  const governance = record(firstValue(envelope, ["governance"]));
  const mutationSources = [
    envelope,
    governance,
    record(firstValue(envelope, ["summary"])),
    record(firstValue(envelope, ["source"])),
    record(firstValue(envelope, ["binding"])),
  ];
  const mutationKeys = [
    ["dataset_mutated", "datasetMutated"],
    ["target_contract_mutated", "targetContractMutated"],
    ["treatment_mutated", "treatmentMutated"],
    ["predictor_authorization_mutated", "predictorAuthorizationMutated"],
    ["analysis_partition_mutated", "analysisPartitionMutated"],
    ["feature_manifest_mutated", "featureManifestMutated"],
  ] as const;
  if (mutationSources.some((source) => mutationKeys.some((keys) => booleanValue(source, keys, false)))) {
    throw new BureauMetadataRequestError({
      status: 409,
      code: "bureau_crosswalk_mutation_conflict",
      kind: "conflict",
      message: "The crosswalk response reported an impermissible modeling mutation.",
      recovery: "Stop and refresh the exact binding. Crosswalk review must remain metadata-only.",
    });
  }
}

function exactCrosswalkPath(projectId: string, identityInput: CanonicalDatasetIdentity): string {
  return exactBindingPath(projectId, identityInput).replace(/\/binding$/, "/crosswalk");
}

function assertCrosswalkLineage(
  governanceInput: unknown,
  expectedIdentity: CanonicalDatasetIdentity,
): void {
  const governance = record(governanceInput);
  const lineage = record(firstValue(governance, ["lineage"]));
  const exact = requireCanonicalDatasetIdentity(expectedIdentity);
  const activation = optionalPositiveInteger(lineage, ["activation_revision", "activationRevision"]);
  if (
    textValue(lineage, ["project_id", "projectId"]) !== exact.project_id ||
    textValue(lineage, ["dataset_id", "datasetId"]) !== exact.dataset_id ||
    textValue(lineage, ["dataset_version_id", "datasetVersionId"]) !== exact.dataset_version_id ||
    (exact.activation_revision !== undefined && activation !== undefined && exact.activation_revision !== activation)
  ) {
    throw new BureauMetadataRequestError({
      status: 409,
      code: "bureau_crosswalk_lineage_conflict",
      kind: "conflict",
      message: "The crosswalk response does not match the requested exact dataset identity.",
      recovery: "Do not save these decisions. Refresh the exact project and dataset version.",
    });
  }
}

function normalizeCrosswalkGovernance(
  payload: unknown,
  expectedIdentity: CanonicalDatasetIdentity,
): BureauCrosswalkGovernance {
  assertCrosswalkNonmutation(payload);
  const envelope = record(payload);
  const governance = record(firstValue(envelope, ["governance", "record", "result"]) ?? envelope);
  assertCrosswalkLineage(governance, expectedIdentity);
  const decisions = listFrom(governance, ["decisions"])
    .map(normalizeCrosswalkDecision)
    .filter((item): item is BureauCrosswalkDecision => item !== null)
    .slice(0, 250);
  const lifecycle = textValue(governance, ["lifecycle_state", "lifecycleState"], "draft");
  const binding = record(firstValue(envelope, ["binding"]));
  const result: BureauCrosswalkGovernance = {
    governanceId: textValue(governance, ["governance_id", "governanceId"]),
    revision: numberValue(governance, ["revision"]),
    revisionChecksum: normalizedChecksum(textValue(governance, ["revision_checksum", "revisionChecksum"])),
    lifecycleState: lifecycle === "confirmed" ? "confirmed" : lifecycle === "review_required" ? "review_required" : "draft",
    sourceCrosswalkId: textValue(governance, ["source_crosswalk_id", "sourceCrosswalkId"]),
    sourceCrosswalkChecksum: normalizedChecksum(textValue(governance, ["source_crosswalk_checksum", "sourceCrosswalkChecksum"])),
    decisions,
    stateCounts: crosswalkCounts(decisions),
    recordedAt: optionalText(record(firstValue(governance, ["audit"])), ["occurred_at", "occurredAt"]),
    bindingRevision: optionalPositiveInteger(binding, ["revision", "binding_revision", "bindingRevision"]),
    bindingLinked: booleanValue(envelope, ["binding_linked", "bindingLinked"], false),
  };
  if (!result.governanceId || !result.revision || !result.revisionChecksum || !decisions.length) {
    throw new BureauMetadataRequestError({
      status: 200,
      code: "bureau_crosswalk_response_incomplete",
      kind: "invalid_response",
      message: "The governed crosswalk response is incomplete.",
      recovery: "Refresh the bounded crosswalk workspace before continuing.",
    });
  }
  return result;
}

export async function previewBureauMetadataCrosswalk(input: {
  projectId: string;
  datasetIdentity: CanonicalDatasetIdentity;
  signal?: AbortSignal;
}): Promise<BureauCrosswalkPreview> {
  const identity = requireCanonicalDatasetIdentity(input.datasetIdentity);
  const payload = await bureauMetadataFetch(
    `${exactCrosswalkPath(input.projectId, identity)}/preview`,
    { signal: input.signal },
  );
  assertCrosswalkNonmutation(payload);
  const envelope = record(payload);
  const source = record(firstValue(envelope, ["source"]));
  const sourceIdentity = {
    project_id: textValue(source, ["project_id", "projectId"]),
    dataset_id: textValue(source, ["dataset_id", "datasetId"]),
    dataset_version_id: textValue(source, ["dataset_version_id", "datasetVersionId"]),
  };
  if (
    sourceIdentity.project_id !== identity.project_id ||
    sourceIdentity.dataset_id !== identity.dataset_id ||
    sourceIdentity.dataset_version_id !== identity.dataset_version_id
  ) {
    throw new BureauMetadataRequestError({
      status: 409,
      code: "bureau_crosswalk_preview_identity_conflict",
      kind: "conflict",
      message: "The bounded candidate preview does not match the exact dataset identity.",
      recovery: "Discard this preview and refresh the exact project binding.",
    });
  }
  const decisions = listFrom(envelope, ["initial_decisions", "initialDecisions"])
    .map(normalizeCrosswalkDecision)
    .filter((item): item is BureauCrosswalkDecision => item !== null)
    .slice(0, 250);
  const candidates = listFrom(source, ["mappings"])
    .map(normalizeCrosswalkCandidate)
    .filter((item): item is BureauCrosswalkCandidate => item !== null)
    .slice(0, 1_000);
  const summary = record(firstValue(envelope, ["summary"]));
  return {
    sourceCrosswalkId: textValue(source, ["crosswalk_id", "crosswalkId"]),
    sourceCrosswalkChecksum: normalizedChecksum(textValue(source, ["crosswalk_checksum", "crosswalkChecksum"])),
    persisted: false,
    candidates,
    decisions,
    stateCounts: crosswalkCounts(decisions),
    authorizedPredictorCount: numberValue(summary, ["authorized_predictor_count", "authorizedPredictorCount"], decisions.length),
    candidateCount: numberValue(summary, ["candidate_count", "candidateCount"], candidates.length),
  };
}

export async function getCurrentBureauMetadataCrosswalk(input: {
  projectId: string;
  datasetIdentity: CanonicalDatasetIdentity;
  signal?: AbortSignal;
}): Promise<BureauCrosswalkGovernance | null> {
  const identity = requireCanonicalDatasetIdentity(input.datasetIdentity);
  const payload = await bureauMetadataFetch(
    `${exactCrosswalkPath(input.projectId, identity)}/current`,
    { signal: input.signal },
    { allowNotFound: true },
  );
  return payload ? normalizeCrosswalkGovernance(payload, identity) : null;
}

export async function getBureauMetadataCrosswalkHistory(input: {
  projectId: string;
  datasetIdentity: CanonicalDatasetIdentity;
  limit?: number;
  signal?: AbortSignal;
}): Promise<BureauCrosswalkHistory> {
  const identity = requireCanonicalDatasetIdentity(input.datasetIdentity);
  const limit = Math.max(1, Math.min(100, Math.floor(input.limit ?? 25)));
  const payload = await bureauMetadataFetch(
    `${exactCrosswalkPath(input.projectId, identity)}/history?limit=${limit}`,
    { signal: input.signal },
  );
  const envelope = record(payload);
  const lineage = record(firstValue(envelope, ["lineage"]));
  assertCrosswalkLineage({ lineage }, identity);
  const revisions = listFrom(envelope, ["revisions"])
    .map((revision) => normalizeCrosswalkGovernance({ governance: revision }, identity))
    .slice(0, limit);
  return {
    returned: numberValue(envelope, ["returned"], revisions.length),
    totalRevisions: numberValue(envelope, ["total_revisions", "totalRevisions"], revisions.length),
    revisions,
  };
}

function decisionRequestPayload(decision: BureauCrosswalkDecisionInput): UnknownRecord {
  return {
    dataset_field: decision.datasetField.trim(),
    mapping_state: decision.mappingState,
    candidate_attribute_code: decision.candidateAttributeCode?.trim() || null,
    alternative_attribute_codes: boundedTextList(decision.alternativeAttributeCodes ?? [], 32),
    source_attribute_codes: boundedTextList(decision.sourceAttributeCodes ?? [], 32),
    rationale: decision.rationale?.trim() || null,
    alias_authority_id: decision.aliasAuthorityId?.trim() || null,
    institutional_alias_reference: decision.institutionalAliasReference?.trim() || null,
    transformation_reference_id: decision.transformationReferenceId?.trim() || null,
    transformation_rule: decision.transformationRule?.trim() || null,
    transformation_or_recoding_concerns: boundedTextList(decision.transformationOrRecodingConcerns ?? [], 16),
    data_type: decision.dataType?.trim() || null,
    units: decision.units?.trim() || null,
    source_system: decision.sourceSystem?.trim() || null,
    timing: decision.timing?.trim() || null,
    special_value_handling: decision.specialValueHandling?.trim() || null,
    value_range_reconciliation: decision.valueRangeReconciliation?.trim() || null,
    special_value_reconciliation: decision.specialValueReconciliation?.trim() || null,
  };
}

export async function saveBureauMetadataCrosswalkDecisions(input: {
  projectId: string;
  datasetIdentity: CanonicalDatasetIdentity;
  expectedCrosswalkRevision: number;
  expectedBindingRevision: number;
  decisions: BureauCrosswalkDecisionInput[];
  analystReason: string;
  confirmCrosswalk?: boolean;
  signal?: AbortSignal;
}): Promise<BureauCrosswalkDecisionResult> {
  const identity = requireCanonicalDatasetIdentity(input.datasetIdentity);
  const decisions = input.decisions.slice(0, 250);
  if (!decisions.length || input.analystReason.trim().length < 8) {
    throw new BureauMetadataRequestError({
      status: 400,
      code: "bureau_crosswalk_explicit_decision_required",
      kind: "invalid_request",
      message: "Select at least one field and provide an analyst reason before saving.",
      recovery: "Review the bounded candidates and record an explicit, evidence-based decision.",
    });
  }
  const payload = await bureauMetadataFetch(
    `${exactCrosswalkPath(input.projectId, identity)}/decisions`,
    {
      method: "POST",
      signal: input.signal,
      body: JSON.stringify({
        expected_crosswalk_revision: Math.max(0, Math.floor(input.expectedCrosswalkRevision)),
        expected_binding_revision: Math.max(1, Math.floor(input.expectedBindingRevision)),
        decisions: decisions.map(decisionRequestPayload),
        analyst_reason: input.analystReason.trim().slice(0, 1_024),
        confirm_crosswalk: input.confirmCrosswalk === true,
      }),
    },
    { allowPartial: true },
  );
  assertCrosswalkNonmutation(payload);
  const envelope = record(payload);
  if (envelope.partial_metadata_state === true) {
    const error = record(firstValue(envelope, ["error"]));
    const revisionChecksum = normalizedChecksum(
      textValue(envelope, ["crosswalk_revision_checksum", "crosswalkRevisionChecksum"]),
    );
    if (!revisionChecksum) {
      throw new BureauMetadataRequestError({
        status: 200,
        code: "bureau_crosswalk_partial_checksum_missing",
        kind: "invalid_response",
        message: "The partial crosswalk response did not include its verifiable revision checksum.",
        recovery: "Refresh the exact current crosswalk before retrying a binding link.",
      });
    }
    return {
      partialMetadataState: true,
      governancePersisted: booleanValue(envelope, ["governance_persisted", "governancePersisted"], true),
      bindingLinked: false,
      governanceId: optionalText(envelope, ["governance_id", "governanceId"]),
      crosswalkRevision: optionalPositiveInteger(envelope, ["crosswalk_revision", "crosswalkRevision"]),
      crosswalkRevisionChecksum: revisionChecksum,
      errorMessage: textValue(error, ["message"], "The decisions were saved, but the exact binding link still requires retry."),
    };
  }
  const governance = normalizeCrosswalkGovernance(payload, identity);
  return {
    partialMetadataState: false,
    governancePersisted: true,
    bindingLinked: governance.bindingLinked,
    governance,
  };
}

export async function retryBureauMetadataCrosswalkBinding(input: {
  projectId: string;
  datasetIdentity: CanonicalDatasetIdentity;
  crosswalkRevision: number;
  expectedBindingRevision: number;
  analystReason: string;
  signal?: AbortSignal;
}): Promise<BureauCrosswalkGovernance> {
  const identity = requireCanonicalDatasetIdentity(input.datasetIdentity);
  const payload = await bureauMetadataFetch(
    `${exactCrosswalkPath(input.projectId, identity)}/binding-link`,
    {
      method: "POST",
      signal: input.signal,
      body: JSON.stringify({
        crosswalk_revision: Math.max(1, Math.floor(input.crosswalkRevision)),
        expected_binding_revision: Math.max(1, Math.floor(input.expectedBindingRevision)),
        analyst_reason: input.analystReason.trim().slice(0, 1_024),
      }),
    },
  );
  return normalizeCrosswalkGovernance(payload, identity);
}
