import { getCachedProjectId } from "./activeProjectContext";
import { getCachedUserId } from "./authSession";
import { loadLocalDataset, localDatasetVersion, type LocalDataset } from "./localDataset";

export type CodeContextLanguage = "python" | "sas";

export type CodeContextFingerprint = {
  schemaVersion: 1;
  datasetId: string;
  datasetVersion: string;
  datasetName: string;
  target: string;
  predictorManifestId: string;
  workflowPage: string;
  language: CodeContextLanguage;
  generatedAt: string;
};

export type EdaCodeContextSeed = {
  datasetId?: string;
  datasetVersion?: string;
  datasetName?: string;
  target?: string;
  predictorManifestId?: string;
  generatedAt?: string;
};

export type CodeDraftScope = {
  userId?: string;
  projectId?: string;
  workflowPage: string;
  language: CodeContextLanguage;
};

export type CodeContextAcknowledgement = {
  draftIdentity: string;
  currentContextIdentity: string;
  acknowledgedAt: string;
};

export type CodeDraftEnvelope = {
  schemaVersion: 1;
  draftId: string;
  code: string;
  context: CodeContextFingerprint | null;
  origin: "user" | "generated_reset" | "legacy_unverified";
  createdAt: string;
  updatedAt: string;
  archivedAt?: string;
  retainedAt?: string;
  acknowledgement?: CodeContextAcknowledgement;
};

export type CodeDraftStore = {
  schemaVersion: 1;
  activeDraftId: string | null;
  drafts: CodeDraftEnvelope[];
};

export type CodeContextMismatchDetail = {
  field: keyof Omit<CodeContextFingerprint, "schemaVersion" | "generatedAt"> | "historicalContext";
  label: string;
  draftValue: string;
  currentValue: string;
};

export type CodeContextEvaluation = {
  matches: boolean;
  requiresAcknowledgement: boolean;
  acknowledged: boolean;
  canUseAsCurrent: boolean;
  warning: string | null;
  details: CodeContextMismatchDetail[];
};

export const CODE_CONTEXT_WARNING = "This edited code was created for a different dataset or target.";
export const CODE_DRAFT_STORAGE_PREFIX = "atlas:code-drafts:v1";
export const EDA_CODE_CONTEXT_SESSION_PREFIX = "atlas:eda-code-context:v1";

const FALLBACK_USER_ID = "anonymous";
const FALLBACK_PROJECT_ID = "unassigned";

type DraftLoadOptions = {
  scope: CodeDraftScope;
  legacyStorageKey?: string;
  legacySectionKey?: string;
  legacyCode?: string;
};

export type LoadedCodeDraft = {
  store: CodeDraftStore;
  draft: CodeDraftEnvelope | null;
  source: "scoped" | "legacy_unverified" | "empty";
};

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function isoNow(): string {
  return new Date().toISOString();
}

export function stableCodeContextHash(value: string): string {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function safeKeyPart(value: string | undefined, fallback: string): string {
  return encodeURIComponent(text(value) || fallback);
}

function scopeWithDefaults(scope: CodeDraftScope): Required<CodeDraftScope> {
  return {
    userId: text(scope.userId) || getCachedUserId() || FALLBACK_USER_ID,
    projectId: text(scope.projectId) || getCachedProjectId() || FALLBACK_PROJECT_ID,
    workflowPage: text(scope.workflowPage) || "unknown-page",
    language: scope.language,
  };
}

export function buildCodeDraftStorageKey(scope: CodeDraftScope): string {
  const resolved = scopeWithDefaults(scope);
  return [
    CODE_DRAFT_STORAGE_PREFIX,
    safeKeyPart(resolved.userId, FALLBACK_USER_ID),
    safeKeyPart(resolved.projectId, FALLBACK_PROJECT_ID),
    safeKeyPart(resolved.workflowPage, "unknown-page"),
    resolved.language,
  ].join(":");
}

export function buildEdaCodeContextSessionKey(userId: string, projectId: string): string {
  return [
    EDA_CODE_CONTEXT_SESSION_PREFIX,
    safeKeyPart(userId, FALLBACK_USER_ID),
    safeKeyPart(projectId, FALLBACK_PROJECT_ID),
  ].join(":");
}

function sessionStorageOrNull(): Storage | null {
  try {
    return typeof sessionStorage === "undefined" ? null : sessionStorage;
  } catch {
    return null;
  }
}

function localStorageOrNull(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/**
 * Step 02 writes the governed workspace identity here after a successful
 * workspace response. The key is user/project scoped and the reader still
 * validates it against the active browser dataset before trusting the
 * predictor-manifest id.
 */
export function writeEdaCodeContextSeed(projectId: string, seed: EdaCodeContextSeed): void {
  const storage = sessionStorageOrNull();
  if (!storage) return;
  const userId = getCachedUserId() || FALLBACK_USER_ID;
  const normalized: EdaCodeContextSeed = {
    datasetId: text(seed.datasetId),
    datasetVersion: text(seed.datasetVersion),
    datasetName: text(seed.datasetName),
    target: text(seed.target),
    predictorManifestId: text(seed.predictorManifestId),
    generatedAt: text(seed.generatedAt) || isoNow(),
  };
  try {
    storage.setItem(buildEdaCodeContextSessionKey(userId, projectId), JSON.stringify(normalized));
    if (typeof window !== "undefined") {
      window.dispatchEvent(
        new CustomEvent("atlas-eda-code-context-updated", {
          detail: { projectId },
        }),
      );
    }
  } catch {
    // A denied/quota-limited session cache falls back to the local dataset
    // fingerprint; it must never break EDA rendering.
  }
}

export function readEdaCodeContextSeed(projectId = getCachedProjectId()): EdaCodeContextSeed | null {
  const storage = sessionStorageOrNull();
  if (!storage) return null;
  const userId = getCachedUserId() || FALLBACK_USER_ID;
  try {
    const parsed = JSON.parse(
      storage.getItem(buildEdaCodeContextSessionKey(userId, projectId || FALLBACK_PROJECT_ID)) || "null",
    ) as EdaCodeContextSeed | null;
    if (!parsed || typeof parsed !== "object") return null;
    return {
      datasetId: text(parsed.datasetId),
      datasetVersion: text(parsed.datasetVersion),
      datasetName: text(parsed.datasetName),
      target: text(parsed.target),
      predictorManifestId: text(parsed.predictorManifestId),
      generatedAt: text(parsed.generatedAt),
    };
  } catch {
    return null;
  }
}

function leafName(value: string): string {
  const normalized = value.replace(/\\/g, "/");
  return normalized.split("/").filter(Boolean).pop() || value;
}

function fallbackDatasetIdentity(dataset: LocalDataset | null, projectId: string) {
  const library = dataset?.dataset_library;
  const access = dataset?.data_access;
  const name = text(library?.datasetName) || text(access?.fileName) || text(access?.sourceLabel) || "Unresolved dataset";
  const versionMaterial = dataset ? localDatasetVersion(dataset) : `${projectId}:no-dataset`;
  return {
    datasetId:
      text(library?.datasetId) ||
      text(access?.datasetId) ||
      `browser-dataset:${stableCodeContextHash(`${projectId}|${name}|${versionMaterial}`)}`,
    datasetVersion:
      text(library?.versionId) ||
      text(dataset?.dataset_version) ||
      text(access?.version) ||
      `browser-version:${stableCodeContextHash(versionMaterial)}`,
    datasetName: leafName(name),
  };
}

function seedMatchesDataset(
  seed: EdaCodeContextSeed | null,
  datasetIdentity: ReturnType<typeof fallbackDatasetIdentity>,
  dataset: LocalDataset | null,
) {
  if (!seed) return false;
  if (text(seed.datasetId) && text(seed.datasetId) !== datasetIdentity.datasetId) return false;
  if (text(seed.datasetVersion) && text(seed.datasetVersion) !== datasetIdentity.datasetVersion) return false;
  if (
    text(seed.datasetName) &&
    leafName(text(seed.datasetName)) !== leafName(datasetIdentity.datasetName)
  ) {
    return false;
  }
  if (text(seed.target) && text(dataset?.target) && text(seed.target) !== text(dataset?.target)) return false;
  return true;
}

export function buildCurrentCodeContext({
  workflowPage,
  language,
  projectId = getCachedProjectId(),
  dataset = loadLocalDataset(),
  generatedAt,
}: {
  workflowPage: string;
  language: CodeContextLanguage;
  projectId?: string;
  dataset?: LocalDataset | null;
  generatedAt?: string;
}): CodeContextFingerprint {
  const resolvedProjectId = text(projectId) || FALLBACK_PROJECT_ID;
  const localIdentity = fallbackDatasetIdentity(dataset, resolvedProjectId);
  const candidateSeed = readEdaCodeContextSeed(resolvedProjectId);
  const seed = seedMatchesDataset(candidateSeed, localIdentity, dataset) ? candidateSeed : null;
  const target = text(seed?.target) || text(dataset?.target) || "No target selected";
  const selectedPredictors = [...(dataset?.selected_columns ?? [])].map(text).filter(Boolean).sort();
  const fallbackManifest = stableCodeContextHash(
    JSON.stringify({
      datasetId: localIdentity.datasetId,
      datasetVersion: localIdentity.datasetVersion,
      target,
      selectedPredictors,
    }),
  );

  return {
    schemaVersion: 1,
    datasetId: text(seed?.datasetId) || localIdentity.datasetId,
    datasetVersion: text(seed?.datasetVersion) || localIdentity.datasetVersion,
    datasetName: leafName(text(seed?.datasetName) || localIdentity.datasetName),
    target,
    predictorManifestId: text(seed?.predictorManifestId) || `browser-selection:${fallbackManifest}`,
    workflowPage: text(workflowPage) || "unknown-page",
    language,
    generatedAt: text(generatedAt) || text(seed?.generatedAt) || isoNow(),
  };
}

/**
 * generatedAt is provenance, not identity: reopening the same governed context
 * must not make an otherwise identical draft stale.
 */
export function codeContextIdentity(context: CodeContextFingerprint): string {
  return stableCodeContextHash(
    JSON.stringify({
      datasetId: context.datasetId,
      datasetVersion: context.datasetVersion,
      datasetName: context.datasetName,
      target: context.target,
      predictorManifestId: context.predictorManifestId,
      workflowPage: context.workflowPage,
      language: context.language,
    }),
  );
}

function safeDisplayValue(value: string): string {
  const withoutControls = value.replace(/[\u0000-\u001f\u007f]/g, " ").trim();
  const safeLeaf = /[\\/]/.test(withoutControls) ? leafName(withoutControls) : withoutControls;
  if (!safeLeaf) return "Not recorded";
  return safeLeaf.length > 96 ? `${safeLeaf.slice(0, 93)}...` : safeLeaf;
}

const COMPARABLE_FIELDS: Array<{
  field: keyof Omit<CodeContextFingerprint, "schemaVersion" | "generatedAt">;
  label: string;
}> = [
  { field: "datasetId", label: "Dataset ID" },
  { field: "datasetVersion", label: "Dataset version" },
  { field: "datasetName", label: "Dataset name" },
  { field: "target", label: "Target" },
  { field: "predictorManifestId", label: "Predictor manifest" },
  { field: "workflowPage", label: "Workflow page" },
  { field: "language", label: "Language" },
];

export function compareCodeContexts(
  draftContext: CodeContextFingerprint | null,
  currentContext: CodeContextFingerprint,
): CodeContextMismatchDetail[] {
  if (!draftContext) {
    return [
      {
        field: "historicalContext",
        label: "Draft context",
        draftValue: "Historical context was not recorded",
        currentValue: `${safeDisplayValue(currentContext.datasetName)} — ${safeDisplayValue(currentContext.target)}`,
      },
    ];
  }
  return COMPARABLE_FIELDS.flatMap(({ field, label }) =>
    draftContext[field] === currentContext[field]
      ? []
      : [
          {
            field,
            label,
            draftValue: safeDisplayValue(String(draftContext[field])),
            currentValue: safeDisplayValue(String(currentContext[field])),
          },
        ],
  );
}

export function codeDraftIdentity(draft: CodeDraftEnvelope, code = draft.code): string {
  const contextPart = draft.context ? codeContextIdentity(draft.context) : `legacy:${draft.draftId}`;
  return stableCodeContextHash(`${contextPart}|${stableCodeContextHash(code)}`);
}

export function evaluateCodeDraftContext(
  draft: CodeDraftEnvelope | null,
  currentContext: CodeContextFingerprint,
  workingCode?: string,
): CodeContextEvaluation {
  if (!draft) {
    return {
      matches: true,
      requiresAcknowledgement: false,
      acknowledged: false,
      canUseAsCurrent: true,
      warning: null,
      details: [],
    };
  }
  const code = workingCode ?? draft.code;
  const details = compareCodeContexts(draft.context, currentContext);
  const matches = details.length === 0;
  const requiresAcknowledgement = Boolean(code.trim()) && !matches;
  const acknowledged =
    requiresAcknowledgement &&
    draft.acknowledgement?.draftIdentity === codeDraftIdentity(draft, code) &&
    draft.acknowledgement?.currentContextIdentity === codeContextIdentity(currentContext);
  return {
    matches,
    requiresAcknowledgement,
    acknowledged,
    canUseAsCurrent: !requiresAcknowledgement || acknowledged,
    warning: requiresAcknowledgement ? CODE_CONTEXT_WARNING : null,
    details,
  };
}

function emptyStore(): CodeDraftStore {
  return { schemaVersion: 1, activeDraftId: null, drafts: [] };
}

function isFingerprint(value: unknown): value is CodeContextFingerprint {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<CodeContextFingerprint>;
  return (
    candidate.schemaVersion === 1 &&
    (candidate.language === "python" || candidate.language === "sas") &&
    typeof candidate.datasetId === "string" &&
    typeof candidate.datasetVersion === "string" &&
    typeof candidate.datasetName === "string" &&
    typeof candidate.target === "string" &&
    typeof candidate.predictorManifestId === "string" &&
    typeof candidate.workflowPage === "string" &&
    typeof candidate.generatedAt === "string"
  );
}

function isEnvelope(value: unknown): value is CodeDraftEnvelope {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<CodeDraftEnvelope>;
  return (
    candidate.schemaVersion === 1 &&
    typeof candidate.draftId === "string" &&
    typeof candidate.code === "string" &&
    (candidate.context === null || isFingerprint(candidate.context)) &&
    (candidate.origin === "user" ||
      candidate.origin === "generated_reset" ||
      candidate.origin === "legacy_unverified") &&
    typeof candidate.createdAt === "string" &&
    typeof candidate.updatedAt === "string"
  );
}

function readScopedStore(scope: CodeDraftScope): CodeDraftStore {
  const storage = localStorageOrNull();
  if (!storage) return emptyStore();
  try {
    const parsed = JSON.parse(storage.getItem(buildCodeDraftStorageKey(scope)) || "null") as Partial<CodeDraftStore> | null;
    if (!parsed || parsed.schemaVersion !== 1 || !Array.isArray(parsed.drafts)) return emptyStore();
    const drafts = parsed.drafts.filter(isEnvelope);
    const requestedActive = typeof parsed.activeDraftId === "string" ? parsed.activeDraftId : null;
    const activeDraftId =
      drafts.find((draft) => draft.draftId === requestedActive && !draft.archivedAt)?.draftId ??
      [...drafts].reverse().find((draft) => !draft.archivedAt)?.draftId ??
      null;
    return { schemaVersion: 1, activeDraftId, drafts };
  } catch {
    return emptyStore();
  }
}

function dispatchDraftUpdate() {
  try {
    if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent("step-code-updated"));
  } catch {
    // A storage update remains valid in non-DOM test environments.
  }
}

function writeScopedStore(scope: CodeDraftScope, store: CodeDraftStore): void {
  const storage = localStorageOrNull();
  if (!storage) return;
  storage.setItem(buildCodeDraftStorageKey(scope), JSON.stringify(store));
  dispatchDraftUpdate();
}

function readLegacyCode(options: DraftLoadOptions): string {
  if (typeof options.legacyCode === "string") return options.legacyCode;
  if (!options.legacyStorageKey || !options.legacySectionKey) return "";
  const storage = localStorageOrNull();
  if (!storage) return "";
  try {
    const parsed = JSON.parse(storage.getItem(options.legacyStorageKey) || "{}") as Record<string, unknown>;
    return typeof parsed?.[options.legacySectionKey] === "string" ? String(parsed[options.legacySectionKey]) : "";
  } catch {
    return "";
  }
}

function legacyEnvelope(options: DraftLoadOptions, code: string): CodeDraftEnvelope {
  const scope = scopeWithDefaults(options.scope);
  const identity = stableCodeContextHash(
    `${scope.userId}|${scope.projectId}|${scope.workflowPage}|${scope.language}|${code}`,
  );
  const timestamp = isoNow();
  return {
    schemaVersion: 1,
    draftId: `legacy_${identity}`,
    code,
    context: null,
    origin: "legacy_unverified",
    createdAt: timestamp,
    updatedAt: timestamp,
  };
}

export function loadCodeDraft(options: DraftLoadOptions): LoadedCodeDraft {
  const store = readScopedStore(options.scope);
  const active = store.drafts.find((draft) => draft.draftId === store.activeDraftId && !draft.archivedAt) ?? null;
  if (active) return { store, draft: active, source: "scoped" };

  const legacyCode = readLegacyCode(options);
  if (!legacyCode.trim()) return { store, draft: null, source: "empty" };
  const draft = legacyEnvelope(options, legacyCode);
  return {
    store: { ...store, activeDraftId: draft.draftId, drafts: [...store.drafts, draft] },
    draft,
    source: "legacy_unverified",
  };
}

function replaceDraft(store: CodeDraftStore, draft: CodeDraftEnvelope): CodeDraftStore {
  const exists = store.drafts.some((item) => item.draftId === draft.draftId);
  return {
    schemaVersion: 1,
    activeDraftId: draft.draftId,
    drafts: exists
      ? store.drafts.map((item) => (item.draftId === draft.draftId ? draft : item))
      : [...store.drafts, draft],
  };
}

function newDraftId(language: CodeContextLanguage): string {
  const random =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID().replace(/-/g, "")
      : `${Math.random().toString(16).slice(2)}${Date.now().toString(16)}`;
  return `${language}_${random}`;
}

export function persistCodeDraft({
  currentContext,
  code,
  ...loadOptions
}: DraftLoadOptions & {
  currentContext: CodeContextFingerprint;
  code: string;
}): { ok: true; draft: CodeDraftEnvelope } | { ok: false; evaluation: CodeContextEvaluation } {
  const loaded = loadCodeDraft(loadOptions);
  const existing = loaded.draft;
  const timestamp = isoNow();
  const working: CodeDraftEnvelope =
    existing === null
      ? {
          schemaVersion: 1,
          draftId: newDraftId(loadOptions.scope.language),
          code,
          context: currentContext,
          origin: "user",
          createdAt: timestamp,
          updatedAt: timestamp,
        }
      : {
          ...existing,
          code,
          updatedAt: timestamp,
        };
  const evaluation = evaluateCodeDraftContext(working, currentContext, code);
  if (!evaluation.canUseAsCurrent) return { ok: false, evaluation };

  const acknowledgement =
    working.acknowledgement?.draftIdentity === codeDraftIdentity(working, code) &&
    working.acknowledgement.currentContextIdentity === codeContextIdentity(currentContext)
      ? working.acknowledgement
      : undefined;
  const draft = { ...working, acknowledgement };
  writeScopedStore(loadOptions.scope, replaceDraft(loaded.store, draft));
  return { ok: true, draft };
}

export function acknowledgeCodeDraftContext({
  currentContext,
  code,
  ...loadOptions
}: DraftLoadOptions & {
  currentContext: CodeContextFingerprint;
  code: string;
}): CodeDraftEnvelope | null {
  const loaded = loadCodeDraft(loadOptions);
  if (!loaded.draft) return null;
  const working = { ...loaded.draft, code, updatedAt: isoNow() };
  const evaluation = evaluateCodeDraftContext(working, currentContext, code);
  if (!evaluation.requiresAcknowledgement) return working;
  const draft: CodeDraftEnvelope = {
    ...working,
    acknowledgement: {
      draftIdentity: codeDraftIdentity(working, code),
      currentContextIdentity: codeContextIdentity(currentContext),
      acknowledgedAt: isoNow(),
    },
  };
  writeScopedStore(loadOptions.scope, replaceDraft(loaded.store, draft));
  return draft;
}

export function retainHistoricalCodeDraft({
  code,
  ...loadOptions
}: DraftLoadOptions & {
  code: string;
}): CodeDraftEnvelope | null {
  const loaded = loadCodeDraft(loadOptions);
  if (!loaded.draft) return null;
  const timestamp = isoNow();
  const draft: CodeDraftEnvelope = {
    ...loaded.draft,
    code,
    updatedAt: timestamp,
    retainedAt: timestamp,
    acknowledgement: undefined,
  };
  writeScopedStore(loadOptions.scope, replaceDraft(loaded.store, draft));
  return draft;
}

export function resetCodeDraftForCurrentContext({
  currentContext,
  generatedCode,
  historicalCode,
  ...loadOptions
}: DraftLoadOptions & {
  currentContext: CodeContextFingerprint;
  generatedCode: string;
  historicalCode: string;
}): { draft: CodeDraftEnvelope; archivedDraft: CodeDraftEnvelope | null } {
  const loaded = loadCodeDraft(loadOptions);
  const timestamp = isoNow();
  const archivedDraft = loaded.draft
    ? {
        ...loaded.draft,
        code: historicalCode,
        updatedAt: timestamp,
        archivedAt: timestamp,
        acknowledgement: undefined,
      }
    : null;
  const drafts = archivedDraft
    ? loaded.store.drafts.map((item) => (item.draftId === archivedDraft.draftId ? archivedDraft : item))
    : loaded.store.drafts;
  const draft: CodeDraftEnvelope = {
    schemaVersion: 1,
    draftId: newDraftId(loadOptions.scope.language),
    code: generatedCode,
    context: currentContext,
    origin: "generated_reset",
    createdAt: timestamp,
    updatedAt: timestamp,
  };
  writeScopedStore(loadOptions.scope, {
    schemaVersion: 1,
    activeDraftId: draft.draftId,
    drafts: [...drafts, draft],
  });
  return { draft, archivedDraft };
}

export function codeContextSummary(context: CodeContextFingerprint | null): string[] {
  if (!context) return ["Draft context: Historical context was not recorded"];
  return [
    `Dataset: ${safeDisplayValue(context.datasetName)}`,
    `Dataset ID: ${safeDisplayValue(context.datasetId)}`,
    `Dataset version: ${safeDisplayValue(context.datasetVersion)}`,
    `Target: ${safeDisplayValue(context.target)}`,
    `Predictor manifest: ${safeDisplayValue(context.predictorManifestId)}`,
    `Workflow page: ${safeDisplayValue(context.workflowPage)}`,
    `Language: ${safeDisplayValue(context.language)}`,
    `Generated: ${safeDisplayValue(context.generatedAt)}`,
  ];
}
