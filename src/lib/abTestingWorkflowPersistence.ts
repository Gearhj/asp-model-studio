export type AbTestingWorkflowStepPayload<TFormValues extends Record<string, unknown> = Record<string, unknown>> = {
  projectId: string;
  workflowType: "ab_testing";
  stepId: string;
  stepNumber?: number;
  stepSlug: string;
  stepRoute?: string;
  formValues: TFormValues;
  calculatedMetrics?: Record<string, unknown>;
  reviewerNotes?: string;
  evidenceStatus?: string;
  completed: boolean;
  updatedAt?: string;
};

export type AbTestingWorkflowSaveResult<TFormValues extends Record<string, unknown> = Record<string, unknown>> = {
  payload: AbTestingWorkflowStepPayload<TFormValues>;
  workflowNodeStorageKey: string;
  auditStorageKey: string;
  payloadBytes: number;
  browserCacheWritten: boolean;
  browserCacheError?: string;
  prunedKeys: string[];
  retriedAfterQuota: boolean;
};

type StorageLike = Pick<Storage, "getItem" | "key" | "removeItem" | "setItem"> & { readonly length: number };

type PruneOptions = {
  currentStepId?: string;
  aggressive?: boolean;
};

export const AB_TESTING_WORKFLOW_TYPE = "ab_testing";
export const WORKFLOW_NODE_STATE_PREFIX = "atlas-workflow-node-state";
export const AB_TESTING_AUDIT_PREFIX = "atlas-ab-testing-workflow-step";
export const AB_TESTING_MAX_PAYLOAD_BYTES = 100 * 1024;

const allowedFormValueKeys = new Set([
  "objective",
  "inputs",
  "assumptions",
  "method",
  "metrics",
  "validation",
  "risks",
  "decision",
  "rationale",
  "notes",
  "numeric",
  "assignmentUnit",
  "allocationMode",
  "blockStratum",
  "selectedExclusions",
  "ab",
]);

const blockedMetricKeys = new Set([
  "datasetRows",
  "previewRows",
  "rows",
  "variableSummaryTable",
  "downstreamSections",
  "charts",
  "chartData",
  "mecEvidenceTypeLists",
  "documentationMappings",
  "cachedDatasetProfile",
  "generatedReports",
  "fullProject",
  "fullWorkflow",
]);

export function workflowNodeStorageKey(projectId: string, stepId: string) {
  return `${WORKFLOW_NODE_STATE_PREFIX}:${projectId}:${stepId}`;
}

export function abTestingAuditStorageKey(projectId: string, stepId: string) {
  return `${AB_TESTING_AUDIT_PREFIX}:${projectId}:${stepId}`;
}

function assertStorageAvailable(storage: StorageLike | undefined): StorageLike {
  if (!storage) throw new Error("Browser localStorage is unavailable.");
  return storage;
}

function textValue(value: unknown, maxLength = 5000) {
  if (typeof value !== "string") return "";
  return value.slice(0, maxLength);
}

function compactArray(value: unknown, maxItems = 20) {
  if (!Array.isArray(value)) return [];
  return value
    .slice(0, maxItems)
    .map((item) => (typeof item === "string" || typeof item === "number" || typeof item === "boolean" ? item : String(item).slice(0, 500)));
}

function compactNumeric(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .filter(([, entry]) => typeof entry === "number" && Number.isFinite(entry))
      .slice(0, 25),
  );
}

function compactAbValues(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const output: Record<string, unknown> = {};
  for (const [key, entry] of Object.entries(value as Record<string, unknown>).slice(0, 200)) {
    if (typeof entry === "string") output[key] = textValue(entry);
    else if (typeof entry === "number" && Number.isFinite(entry)) output[key] = entry;
    else if (typeof entry === "boolean") output[key] = entry;
    else if (Array.isArray(entry)) output[key] = compactArray(entry, 100);
  }
  return output;
}

export function compactFormValues(input: Record<string, unknown> = {}) {
  const output: Record<string, unknown> = {};
  for (const key of allowedFormValueKeys) {
    const value = input[key];
    if (value == null) continue;
    if (key === "metrics" || key === "selectedExclusions") output[key] = compactArray(value);
    else if (key === "ab") output[key] = compactAbValues(value);
    else if (key === "numeric") output[key] = compactNumeric(value);
    else if (typeof value === "string") output[key] = textValue(value);
    else if (typeof value === "number" || typeof value === "boolean") output[key] = value;
  }
  return output;
}

export function compactCalculatedMetrics(input: Record<string, unknown> = {}) {
  const output: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(input)) {
    if (blockedMetricKeys.has(key)) continue;
    if (typeof value === "string") output[key] = textValue(value, 1000);
    else if (typeof value === "number" || typeof value === "boolean") output[key] = value;
    else if (Array.isArray(value)) output[key] = compactArray(value, 10);
  }
  return output;
}

export function compactAbTestingStepPayload<TFormValues extends Record<string, unknown>>(
  input: AbTestingWorkflowStepPayload<TFormValues>,
): AbTestingWorkflowStepPayload<Record<string, unknown>> {
  return {
    projectId: input.projectId,
    workflowType: AB_TESTING_WORKFLOW_TYPE,
    stepId: input.stepId,
    stepNumber: input.stepNumber,
    stepSlug: input.stepSlug,
    stepRoute: input.stepRoute,
    formValues: compactFormValues(input.formValues),
    reviewerNotes: textValue(input.reviewerNotes ?? ""),
    calculatedMetrics: compactCalculatedMetrics(input.calculatedMetrics),
    evidenceStatus: input.evidenceStatus ? textValue(input.evidenceStatus, 100) : undefined,
    completed: Boolean(input.completed),
    updatedAt: input.updatedAt ?? new Date().toISOString(),
  };
}

export function serializedByteSize(value: string) {
  if (typeof Blob !== "undefined") return new Blob([value]).size;
  return new TextEncoder().encode(value).byteLength;
}

export function safeSetLocalStorage(storage: Pick<Storage, "setItem">, key: string, value: string): { ok: boolean; error?: string } {
  try {
    storage.setItem(key, value);
    return { ok: true };
  } catch (error) {
    if (typeof DOMException !== "undefined" && error instanceof DOMException && error.name === "QuotaExceededError") {
      return { ok: false, error: "Local storage quota exceeded." };
    }
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}

function isQuotaErrorMessage(message?: string) {
  return Boolean(message && /quota|exceed/i.test(message));
}

export function pruneAbTestingWorkflowStorage(
  projectId: string,
  storageOrOptions?: StorageLike | PruneOptions,
  maybeOptions?: PruneOptions,
) {
  const storage = storageOrOptions && "setItem" in storageOrOptions ? storageOrOptions : typeof localStorage === "undefined" ? undefined : localStorage;
  const options = storageOrOptions && "setItem" in storageOrOptions ? maybeOptions : storageOrOptions;
  const currentStepId = options?.currentStepId;
  const aggressive = Boolean(options?.aggressive);
  const activeStorage = assertStorageAvailable(storage);
  const prefixes = [`${AB_TESTING_AUDIT_PREFIX}:${projectId}:`, `${WORKFLOW_NODE_STATE_PREFIX}:${projectId}:ab-testing-`];
  const keysToRemove: string[] = [];
  for (let index = 0; index < activeStorage.length; index += 1) {
    const key = activeStorage.key(index);
    if (!key || !prefixes.some((prefix) => key.startsWith(prefix))) continue;
    const isCurrentStepKey = Boolean(currentStepId && (key === abTestingAuditStorageKey(projectId, currentStepId) || key === workflowNodeStorageKey(projectId, currentStepId)));
    const value = activeStorage.getItem(key) ?? "";
    if (
      isCurrentStepKey ||
      aggressive ||
      value.length > AB_TESTING_MAX_PAYLOAD_BYTES ||
      /datasetRows|previewRows|variableSummaryTable|cachedDatasetProfile|fullProject|fullWorkflow/.test(value)
    ) {
      keysToRemove.push(key);
    }
  }
  keysToRemove.forEach((key) => activeStorage.removeItem(key));
  return keysToRemove;
}

export function clearAbTestingWorkflowStorage(projectId: string, storage: StorageLike | undefined = typeof localStorage === "undefined" ? undefined : localStorage) {
  const activeStorage = assertStorageAvailable(storage);
  const prefixes = [`${AB_TESTING_AUDIT_PREFIX}:${projectId}:`, `${WORKFLOW_NODE_STATE_PREFIX}:${projectId}:ab-testing-`];
  const keysToRemove: string[] = [];
  for (let index = 0; index < activeStorage.length; index += 1) {
    const key = activeStorage.key(index);
    if (key && prefixes.some((prefix) => key.startsWith(prefix))) keysToRemove.push(key);
  }
  keysToRemove.forEach((key) => activeStorage.removeItem(key));
  return keysToRemove;
}

function writeCompactAbTestingCache(
  storage: StorageLike,
  workflowKey: string,
  workflowSerialized: string,
  auditKey: string,
  serialized: string,
) {
  const workflowResult = safeSetLocalStorage(storage as Storage, workflowKey, workflowSerialized);
  if (!workflowResult.ok) return workflowResult;
  return safeSetLocalStorage(storage as Storage, auditKey, serialized);
}

export function loadAbTestingStep<TFormValues extends Record<string, unknown> = Record<string, unknown>>(
  projectId: string,
  stepId: string,
  storage: StorageLike | undefined = typeof localStorage === "undefined" ? undefined : localStorage,
) {
  const activeStorage = assertStorageAvailable(storage);
  const workflowRaw = activeStorage.getItem(workflowNodeStorageKey(projectId, stepId));
  if (workflowRaw) return JSON.parse(workflowRaw) as TFormValues;

  const auditRaw = activeStorage.getItem(abTestingAuditStorageKey(projectId, stepId));
  if (!auditRaw) return null;
  const auditPayload = JSON.parse(auditRaw) as AbTestingWorkflowStepPayload<TFormValues>;
  return auditPayload.formValues ?? null;
}

export function saveAbTestingStep<TFormValues extends Record<string, unknown>>(
  payload: AbTestingWorkflowStepPayload<TFormValues>,
  storage: StorageLike | undefined = typeof localStorage === "undefined" ? undefined : localStorage,
): AbTestingWorkflowSaveResult<Record<string, unknown>> {
  const activeStorage = assertStorageAvailable(storage);
  const prunedKeys = pruneAbTestingWorkflowStorage(payload.projectId, activeStorage, { currentStepId: payload.stepId });

  const completedPayload = compactAbTestingStepPayload(payload);
  const serialized = JSON.stringify(completedPayload);
  const payloadBytes = serializedByteSize(serialized);
  if (payloadBytes > AB_TESTING_MAX_PAYLOAD_BYTES) {
    throw new Error("A/B Testing step payload is too large to save. Large derived artifacts must be stored as server artifacts, not browser state.");
  }

  const workflowKey = workflowNodeStorageKey(completedPayload.projectId, completedPayload.stepId);
  const auditKey = abTestingAuditStorageKey(completedPayload.projectId, completedPayload.stepId);
  const workflowSerialized = JSON.stringify(completedPayload.formValues);

  let retriedAfterQuota = false;
  let writeResult = writeCompactAbTestingCache(activeStorage, workflowKey, workflowSerialized, auditKey, serialized);
  if (!writeResult.ok && isQuotaErrorMessage(writeResult.error)) {
    retriedAfterQuota = true;
    prunedKeys.push(...pruneAbTestingWorkflowStorage(payload.projectId, activeStorage, { currentStepId: payload.stepId, aggressive: true }));
    writeResult = writeCompactAbTestingCache(activeStorage, workflowKey, workflowSerialized, auditKey, serialized);
  }
  const browserCacheWritten = writeResult.ok;
  const browserCacheError = writeResult.error;

  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("atlas-workflow-node-updated"));
    window.dispatchEvent(
      new CustomEvent("atlas-ab-testing-workflow-step-saved", {
        detail: {
          projectId: completedPayload.projectId,
          stepId: completedPayload.stepId,
          stepSlug: completedPayload.stepSlug,
          savedAt: completedPayload.updatedAt,
          workflowNodeStorageKey: workflowKey,
          auditStorageKey: auditKey,
          payloadBytes,
          browserCacheWritten,
          browserCacheError,
          prunedKeys,
          retriedAfterQuota,
        },
      }),
    );
  }

  return {
    payload: completedPayload,
    workflowNodeStorageKey: workflowKey,
    auditStorageKey: auditKey,
    payloadBytes,
    browserCacheWritten,
    browserCacheError,
    prunedKeys,
    retriedAfterQuota,
  };
}
