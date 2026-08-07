import { DATASET_API_BASE } from "./datasetLibrary";

const ATTRIBUTE_QUERY_LIMIT = 120;
export const BUREAU_CATALOG_PAGE_SIZE = 25;
export const BUREAU_CATALOG_MAX_PAGE_SIZE = 50;

type UnknownRecord = Record<string, unknown>;

export type BureauCatalogVersion = {
  versionId: string;
  catalogId: string;
  provider: string;
  product: string;
  edition: string;
  dictionaryVersion: string;
  catalogChecksum: string;
  attributeCount: number;
  specialValueCount: number;
  validationFindingCount: number;
  integrityStatus: string;
  installStatus: string;
  entitlementStatus: string;
  lifecycleStatus: string;
  validationStatus: string;
  installedAt?: string;
  validatedAt?: string;
  retiredAt?: string;
};

export type BureauCatalogAttributeSummary = {
  attributeCode: string;
  displayName: string;
  description: string;
  units: string;
  fieldLength?: number;
  ordinaryValidMin?: string;
  ordinaryValidMax?: string;
  validRangeExpression: string;
  specialValueCount?: number;
  reviewStatus: string;
};

export type BureauCatalogAttributeDetail = BureauCatalogAttributeSummary & {
  provider: string;
  product: string;
  edition: string;
  dictionaryVersion: string;
  validValueExpression: string;
  numericType: string;
  crossBureauAvailability: string[];
  levelingStatus: string;
  archiveAvailability: string;
  reconciliationStatus: string;
  extractionConfidence?: number;
  sourcePage?: number;
};

export type BureauCatalogAttributePage = {
  attributes: BureauCatalogAttributeSummary[];
  query: string;
  offset: number;
  limit: number;
  total?: number;
  hasNext: boolean;
};

export class BureauCatalogAdminRequestError extends Error {
  readonly status: number;
  readonly code: string;
  readonly recovery: string;
  readonly denied: boolean;
  readonly retryable: boolean;

  constructor(input: {
    status: number;
    code: string;
    message: string;
    recovery: string;
    retryable?: boolean;
  }) {
    super(input.message);
    this.name = "BureauCatalogAdminRequestError";
    this.status = input.status;
    this.code = input.code;
    this.recovery = input.recovery;
    this.denied = input.status === 401 || input.status === 403;
    this.retryable = input.retryable ?? input.status >= 500;
  }
}

function isRecord(value: unknown): value is UnknownRecord {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function record(value: unknown): UnknownRecord {
  return isRecord(value) ? value : {};
}

function firstValue(source: UnknownRecord, keys: string[]): unknown {
  for (const key of keys) {
    if (source[key] !== undefined && source[key] !== null) return source[key];
  }
  return undefined;
}

function textValue(source: UnknownRecord, keys: string[], fallback = "") {
  const value = firstValue(source, keys);
  if (value === undefined || value === null) return fallback;
  return String(value).trim().slice(0, 1_000);
}

function numberValue(source: UnknownRecord, keys: string[], fallback = 0) {
  const value = Number(firstValue(source, keys));
  return Number.isFinite(value) && value >= 0 ? value : fallback;
}

function optionalNumber(source: UnknownRecord, keys: string[]) {
  const raw = firstValue(source, keys);
  if (raw === undefined || raw === null || raw === "") return undefined;
  const value = Number(raw);
  return Number.isFinite(value) ? value : undefined;
}

function optionalText(source: UnknownRecord, keys: string[]) {
  const value = textValue(source, keys);
  return value || undefined;
}

function stringList(source: UnknownRecord, keys: string[]) {
  const value = firstValue(source, keys);
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item).trim().slice(0, 160)).filter(Boolean).slice(0, 12);
}

function normalizeVersion(input: unknown): BureauCatalogVersion {
  const source = record(input);
  const key = record(firstValue(source, ["catalog_key", "catalogKey", "key"]));
  const integrity = record(firstValue(source, ["integrity", "integrity_state", "integrityState"]));
  const installation = record(firstValue(source, ["installation", "install", "install_state", "installState"]));
  const entitlement = record(firstValue(source, ["entitlement", "entitlement_state", "entitlementState"]));
  return {
    versionId: textValue(source, ["catalog_version_id", "catalogVersionId", "version_id", "versionId", "id"]),
    catalogId: textValue(source, ["catalog_id", "catalogId"]),
    provider: textValue(source, ["provider_name", "providerName", "provider"], textValue(key, ["provider"], "Unknown provider")),
    product: textValue(source, ["product_name", "productName", "product"], textValue(key, ["product"], "Unknown product")),
    edition: textValue(source, ["edition"], textValue(key, ["edition"], "Unknown edition")),
    dictionaryVersion: textValue(
      source,
      ["source_release_version", "sourceReleaseVersion", "dictionary_version", "dictionaryVersion"],
      textValue(key, ["dictionary_version", "dictionaryVersion"], "Unknown version"),
    ),
    catalogChecksum: textValue(source, ["normalized_catalog_checksum", "normalizedCatalogChecksum", "catalog_checksum", "catalogChecksum", "checksum"]),
    attributeCount: numberValue(source, ["record_count", "recordCount", "attribute_count", "attributeCount"]),
    specialValueCount: numberValue(source, ["special_value_definition_count", "specialValueDefinitionCount", "special_value_count", "specialValueCount"]),
    validationFindingCount: numberValue(source, ["validation_finding_count", "validationFindingCount"]),
    integrityStatus: textValue(
      source,
      ["integrity_status", "integrityStatus"],
      textValue(integrity, ["status"], "unknown"),
    ),
    installStatus: textValue(
      source,
      ["installation_status", "installationStatus", "install_status", "installStatus"],
      textValue(installation, ["status"], "unknown"),
    ),
    entitlementStatus: textValue(
      source,
      ["entitlement_status", "entitlementStatus"],
      textValue(entitlement, ["status"], "entitled"),
    ),
    lifecycleStatus: textValue(source, ["retired_status", "retiredStatus", "lifecycle_status", "lifecycleStatus", "status"], textValue(source, ["supersession_status", "supersessionStatus"], "unknown")),
    validationStatus: textValue(source, ["validation_status", "validationStatus"], textValue(source, ["integrity_status", "integrityStatus"], "unknown")),
    installedAt: optionalText(source, ["installed_at", "installedAt", "created_at", "createdAt"]),
    validatedAt: optionalText(source, ["validated_at", "validatedAt"]),
    retiredAt: optionalText(source, ["retired_at", "retiredAt"]),
  };
}

function normalizeAttributeSummary(input: unknown): BureauCatalogAttributeSummary {
  const source = record(input);
  return {
    attributeCode: textValue(source, ["attribute_code", "attributeCode", "code"]),
    displayName: textValue(source, ["display_name", "displayName", "label"]),
    description: textValue(source, ["description", "summary"]),
    units: textValue(source, ["units"]),
    fieldLength: optionalNumber(source, ["field_length", "fieldLength"]),
    ordinaryValidMin: optionalText(source, ["ordinary_valid_min", "ordinaryValidMin", "ordinary_min", "ordinaryMin"]),
    ordinaryValidMax: optionalText(source, ["ordinary_valid_max", "ordinaryValidMax", "ordinary_max", "ordinaryMax"]),
    validRangeExpression: textValue(source, ["valid_range_expression", "validRangeExpression", "valid_value_expression", "validValueExpression"]),
    specialValueCount: optionalNumber(source, ["special_value_count", "specialValueCount"]),
    reviewStatus: textValue(source, ["review_status", "reviewStatus"], "not recorded"),
  };
}

function normalizeAttributeDetail(input: unknown): BureauCatalogAttributeDetail {
  const source = record(input);
  const key = record(firstValue(source, ["catalog_key", "catalogKey", "key"]));
  return {
    ...normalizeAttributeSummary(source),
    provider: textValue(source, ["provider"], textValue(key, ["provider"])),
    product: textValue(source, ["product"], textValue(key, ["product"])),
    edition: textValue(source, ["edition"], textValue(key, ["edition"])),
    dictionaryVersion: textValue(
      source,
      ["dictionary_version", "dictionaryVersion"],
      textValue(key, ["dictionary_version", "dictionaryVersion"]),
    ),
    validValueExpression: textValue(source, ["valid_range_expression", "validRangeExpression", "valid_value_expression", "validValueExpression"]),
    numericType: textValue(source, ["numeric_type", "numericType"]),
    crossBureauAvailability: stringList(source, ["cross_bureau_availability", "crossBureauAvailability"]),
    levelingStatus: textValue(source, ["leveling_indicator", "levelingIndicator", "leveling_status", "levelingStatus"], "not recorded"),
    archiveAvailability: textValue(source, ["archive_indicator", "archiveIndicator", "archive_availability", "archiveAvailability"], "not recorded"),
    reconciliationStatus: textValue(source, ["reconciliation_status", "reconciliationStatus"], "not recorded"),
    extractionConfidence: optionalNumber(source, ["extraction_confidence", "extractionConfidence"]),
    sourcePage: optionalNumber(source, ["source_page", "sourcePage"]),
  };
}

function safeError(status: number, payload: unknown) {
  const body = record(payload);
  const detail = record(body.detail);
  const code = textValue(detail, ["code"], textValue(body, ["code"], "bureau_catalog_admin_request_failed"));
  if (status === 401) {
    return new BureauCatalogAdminRequestError({
      status,
      code,
      message: "Your ATLAS session is not authenticated for catalog administration.",
      recovery: "Sign in again, then return to Bureau Catalog Administration.",
    });
  }
  if (status === 403) {
    return new BureauCatalogAdminRequestError({
      status,
      code,
      message: "Bureau catalog administration is restricted to entitled platform administrators.",
      recovery: "Ask an ATLAS platform administrator to confirm your role and catalog entitlement.",
    });
  }
  if (status === 404) {
    return new BureauCatalogAdminRequestError({
      status,
      code,
      message: "The exact catalog version or attribute was not found.",
      recovery: "Confirm the exact version and attribute code. ATLAS will not fall back to another version.",
    });
  }
  if (status === 409) {
    return new BureauCatalogAdminRequestError({
      status,
      code,
      message: "The catalog state changed before this action could be completed.",
      recovery: "Refresh the catalog inventory and review the current exact version before retrying.",
    });
  }
  return new BureauCatalogAdminRequestError({
    status,
    code,
    message:
      status >= 500
        ? "The restricted bureau catalog service is temporarily unavailable."
        : "ATLAS could not complete the restricted catalog request.",
    recovery:
      status >= 500
        ? "Retry after the service is available; no catalog state was changed by this response."
        : "Review the request and retry without changing the exact catalog version.",
  });
}

async function catalogFetch(path: string, init?: RequestInit): Promise<unknown> {
  const response = await fetch(`${DATASET_API_BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers ?? {}),
    },
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || (isRecord(payload) && payload.ok === false)) {
    throw safeError(response.status, payload);
  }
  if (!payload) {
    throw new BureauCatalogAdminRequestError({
      status: response.status,
      code: "bureau_catalog_admin_empty_response",
      message: "ATLAS returned an empty restricted catalog response.",
      recovery: "Refresh the page. No catalog state was changed by the empty response.",
    });
  }
  return payload;
}

function listFrom(payload: unknown, keys: string[]) {
  if (Array.isArray(payload)) return payload;
  const source = record(payload);
  for (const key of keys) {
    if (Array.isArray(source[key])) return source[key] as unknown[];
  }
  return [];
}

export function checksumPrefix(checksum: string, length = 12) {
  const normalized = checksum.trim().toLowerCase();
  if (!normalized) return "Not available";
  return `${normalized.slice(0, Math.max(8, Math.min(length, 16)))}...`;
}

export async function listEntitledBureauCatalogVersions(): Promise<BureauCatalogVersion[]> {
  const payload = await catalogFetch("/admin/bureau-catalogs");
  return listFrom(payload, ["catalogs", "versions", "items"]).map(normalizeVersion);
}

export const listBureauCatalogVersions = listEntitledBureauCatalogVersions;

export async function validateBureauCatalogVersion(versionId: string): Promise<BureauCatalogVersion> {
  const payload = record(
    await catalogFetch(`/admin/bureau-catalogs/${encodeURIComponent(versionId)}/validate`, {
      method: "POST",
      body: JSON.stringify({}),
    }),
  );
  return normalizeVersion(firstValue(payload, ["catalog", "version", "result"]) ?? payload);
}

export async function retireBureauCatalogVersion(versionId: string): Promise<BureauCatalogVersion> {
  const payload = record(
    await catalogFetch(`/admin/bureau-catalogs/${encodeURIComponent(versionId)}/retire`, {
      method: "POST",
      body: JSON.stringify({}),
    }),
  );
  return normalizeVersion(firstValue(payload, ["catalog", "version", "result"]) ?? payload);
}

export async function searchBureauCatalogAttributes(input: {
  versionId: string;
  query?: string;
  offset?: number;
  limit?: number;
}): Promise<BureauCatalogAttributePage> {
  const query = String(input.query ?? "").trim().slice(0, ATTRIBUTE_QUERY_LIMIT);
  if (!query) {
    throw new BureauCatalogAdminRequestError({
      status: 400,
      code: "bureau_catalog_search_query_required",
      message: "Enter an attribute code or search term.",
      recovery: "Catalog access is deliberately bounded and does not support an unfiltered full scan.",
      retryable: false,
    });
  }
  const offset = Math.max(0, Math.floor(Number(input.offset) || 0));
  const limit = Math.max(1, Math.min(BUREAU_CATALOG_MAX_PAGE_SIZE, Math.floor(Number(input.limit) || BUREAU_CATALOG_PAGE_SIZE)));
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  if (query) params.set("q", query);
  const payload = record(
    await catalogFetch(
      `/admin/bureau-catalogs/${encodeURIComponent(input.versionId)}/attributes?${params.toString()}`,
    ),
  );
  const attributes = listFrom(payload, ["attributes", "items", "results"]).map(normalizeAttributeSummary);
  const pagination = record(firstValue(payload, ["pagination", "page"]));
  const totalRaw = firstValue(payload, ["total", "total_count", "totalCount"]) ?? firstValue(pagination, ["total", "total_count", "totalCount"]);
  const total = totalRaw === undefined || totalRaw === null ? undefined : numberValue({ total: totalRaw }, ["total"]);
  const effectiveOffset = numberValue(payload, ["offset"], numberValue(pagination, ["offset"], offset));
  const effectiveLimit = numberValue(payload, ["limit"], numberValue(pagination, ["limit"], limit));
  const explicitHasNext = firstValue(payload, ["has_more", "hasMore", "has_next", "hasNext"]);
  return {
    attributes,
    query,
    offset: effectiveOffset,
    limit: effectiveLimit || limit,
    total,
    hasNext: typeof explicitHasNext === "boolean" ? explicitHasNext : total !== undefined && effectiveOffset + attributes.length < total,
  };
}

export async function getExactBureauCatalogAttribute(versionId: string, attributeCode: string) {
  const code = attributeCode.trim().slice(0, 128);
  if (!code) {
    throw new BureauCatalogAdminRequestError({
      status: 400,
      code: "bureau_catalog_attribute_code_required",
      message: "Enter an exact attribute code.",
      recovery: "Attribute lookup is exact and will not select a similar code automatically.",
      retryable: false,
    });
  }
  const payload = record(
    await catalogFetch(
      `/admin/bureau-catalogs/${encodeURIComponent(versionId)}/attributes/${encodeURIComponent(code)}`,
    ),
  );
  return normalizeAttributeDetail(firstValue(payload, ["attribute", "result"]) ?? payload);
}
