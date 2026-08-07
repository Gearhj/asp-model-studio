import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Database,
  Eye,
  Link2,
  Loader2,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import {
  BureauMetadataRequestError,
  confirmBureauMetadataBinding,
  getBureauMetadataBinding,
  listEntitledBureauCatalogs,
  previewBureauMetadataBinding,
  type BureauCatalogOption,
  type BureauMetadataBindingPreview,
  type BureauMetadataBindingSummary,
  type BureauMetadataMappingCounts,
} from "../lib/bureauMetadata";
import type { CanonicalDatasetIdentity } from "../lib/datasetIdentity";
import BureauMetadataCrosswalkWorkspace from "./BureauMetadataCrosswalkWorkspace";

type BureauMetadataBindingPanelProps = {
  projectId: string;
  datasetIdentity: CanonicalDatasetIdentity | null;
  featureNames: string[];
  sourceLabel?: string;
  enabled: boolean;
};

type LoadState = "idle" | "loading" | "ready" | "unavailable";

const BUREAU_FIELD_SIGNAL =
  /(?:fico|riskestimate|trad(?:e|es)|delinq|derog|revolv|install|mortgage|bankrupt|publicrec|utilization|inquir)/i;
const BUREAU_SOURCE_SIGNAL = /(?:\bbureau\b|\bheloc\b|credit[\s_-]*(?:report|bureau)|tradeline)/i;

export function isLikelyBureauMetadataContext(
  featureNames: readonly string[],
  sourceLabel = "",
): boolean {
  if (BUREAU_SOURCE_SIGNAL.test(sourceLabel)) return true;
  let matches = 0;
  for (const name of featureNames) {
    if (BUREAU_FIELD_SIGNAL.test(name)) matches += 1;
    if (matches >= 2) return true;
  }
  return false;
}

function CountCard({ label, value, tone = "slate" }: { label: string; value: number; tone?: "slate" | "blue" | "amber" | "rose" }) {
  const toneClass = {
    slate: "border-slate-200 bg-white text-slate-950",
    blue: "border-blue-200 bg-blue-50 text-blue-950",
    amber: "border-amber-200 bg-amber-50 text-amber-950",
    rose: "border-rose-200 bg-rose-50 text-rose-950",
  }[tone];
  return (
    <div className={`rounded-lg border px-3 py-2 ${toneClass}`}>
      <div className="text-[10px] font-bold uppercase tracking-wide opacity-70">{label}</div>
      <div className="mt-1 text-base font-semibold tabular-nums">{value.toLocaleString()}</div>
    </div>
  );
}

function MappingCounts({ counts }: { counts: BureauMetadataMappingCounts }) {
  return (
    <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4" data-testid="bureau-metadata-mapping-counts">
      <CountCard label="Authoritative" value={counts.authoritative} tone="blue" />
      <CountCard label="Review required" value={counts.reviewRequired} tone="amber" />
      <CountCard label="Unresolved" value={counts.unresolved} tone="rose" />
      <CountCard label="Special definitions" value={counts.specialDefinitions} />
    </div>
  );
}

function statusClass(value: string): string {
  const normalized = value.trim().toLowerCase();
  if (["active", "authorized", "verified", "current"].includes(normalized)) {
    return "border-emerald-200 bg-emerald-50 text-emerald-800";
  }
  if (["stale", "review", "review_required", "unknown"].includes(normalized)) {
    return "border-amber-200 bg-amber-50 text-amber-800";
  }
  return "border-slate-200 bg-slate-50 text-slate-700";
}

function safeActionError(error: unknown): BureauMetadataRequestError {
  return error instanceof BureauMetadataRequestError
    ? error
    : new BureauMetadataRequestError({
        status: 0,
        code: "bureau_metadata_action_unavailable",
        kind: "unavailable",
        message: "ATLAS could not complete the bureau metadata action.",
        recovery: "Retry against the current exact identity. No binding or workflow state was changed.",
      });
}

function StatusBadge({ label, value }: { label: string; value: string }) {
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-1 text-[10px] font-bold uppercase tracking-wide ${statusClass(value)}`}>
      {label}: {value || "Not reported"}
    </span>
  );
}

function catalogLabel(catalog: BureauCatalogOption): string {
  return `${catalog.provider} · ${catalog.product} · ${catalog.dictionaryVersion} (${catalog.catalogVersionId})`;
}

function BindingSummary({ binding }: { binding: BureauMetadataBindingSummary }) {
  return (
    <div className="space-y-3" data-testid="bureau-metadata-confirmed-summary">
      <div className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-slate-200 bg-white p-3">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-wide text-slate-500">Exact catalog version</div>
          <div className="mt-1 text-sm font-semibold text-slate-950">
            {binding.identity.provider} · {binding.identity.product}
          </div>
          <div className="mt-1 text-xs text-slate-600">
            {binding.identity.edition} · {binding.identity.dictionaryVersion} · {binding.identity.catalogVersionId}
          </div>
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          <StatusBadge label="Entitlement" value={binding.entitlementState} />
          <StatusBadge label="Integrity" value={binding.integrityState} />
          <StatusBadge label="Binding" value={binding.stale ? "stale" : binding.current ? "current" : binding.status} />
        </div>
      </div>

      {binding.stale ? (
        <div className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-950">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <span>
            This binding is stale{binding.staleReason ? `: ${binding.staleReason}` : "."} Prepare a new exact preview before relying on its mapping summary.
          </span>
        </div>
      ) : (
        <div className="flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs leading-5 text-emerald-950">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <span>The exact dataset version and catalog version have a current, checksum-verified binding.</span>
        </div>
      )}

      <MappingCounts counts={binding.mappingCounts} />

      <div className="grid gap-2 text-xs sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
          <div className="font-semibold text-slate-700">Binding revision</div>
          <div className="mt-1 text-slate-950">{binding.bindingRevision || "Not reported"}</div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
          <div className="font-semibold text-slate-700">Crosswalk revision</div>
          <div className="mt-1 text-slate-950">{binding.crosswalkRevision ?? "Not established"}</div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
          <div className="font-semibold text-slate-700">Evidence</div>
          <div className="mt-1 text-slate-950">{binding.evidenceCount.toLocaleString()} governed reference(s)</div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
          <div className="font-semibold text-slate-700">Activation revision</div>
          <div className="mt-1 text-slate-950">{binding.identity.activationRevision ?? "Backend current"}</div>
        </div>
      </div>
      <p className="text-xs leading-5 text-slate-500">
        Evidence remains in its governed authority. This summary retains only bounded evidence references
        {binding.evidenceKinds.length ? ` (${binding.evidenceKinds.join(", ")})` : ""}; restricted catalog definitions are not stored in the browser.
      </p>
    </div>
  );
}

function PreviewSummary({
  preview,
  catalog,
}: {
  preview: BureauMetadataBindingPreview;
  catalog: BureauCatalogOption;
}) {
  return (
    <div className="space-y-3 rounded-xl border border-blue-300 bg-blue-50 p-4" data-testid="bureau-metadata-binding-preview">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-wide text-blue-700">Candidate preview · not authoritative</div>
          <div className="mt-1 text-sm font-semibold text-blue-950">{catalogLabel(catalog)}</div>
        </div>
        <div className="flex flex-wrap gap-2">
          <StatusBadge label="Entitlement" value={preview.entitlementState} />
          <StatusBadge label="Integrity" value={preview.integrityState} />
          <StatusBadge label="Preview" value={preview.stale ? "stale" : preview.current ? "current" : "review"} />
        </div>
      </div>
      <MappingCounts counts={preview.mappingCounts} />
      <div className="flex items-start gap-2 rounded-lg border border-blue-200 bg-white px-3 py-2 text-xs leading-5 text-blue-950">
        <Eye className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        <span>
          This preview created no authoritative mapping and changed no dataset, treatment, predictor authorization, Analysis Partition, or workflow decision.
          Confirmation creates only the exact governed binding and its evidence references.
        </span>
      </div>
    </div>
  );
}

export default function BureauMetadataBindingPanel({
  projectId,
  datasetIdentity,
  featureNames,
  sourceLabel = "",
  enabled,
}: BureauMetadataBindingPanelProps) {
  const likelyBureau = useMemo(
    () => isLikelyBureauMetadataContext(featureNames, sourceLabel),
    [featureNames, sourceLabel],
  );
  const [explicitlyOpened, setExplicitlyOpened] = useState(false);
  const shouldLoad = likelyBureau || explicitlyOpened;
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [catalogs, setCatalogs] = useState<BureauCatalogOption[]>([]);
  const [binding, setBinding] = useState<BureauMetadataBindingSummary | null>(null);
  const [selectedCatalogVersionId, setSelectedCatalogVersionId] = useState("");
  const [preview, setPreview] = useState<BureauMetadataBindingPreview | null>(null);
  const [analystRationale, setAnalystRationale] = useState("");
  const [requestError, setRequestError] = useState<BureauMetadataRequestError | null>(null);
  const [actionPending, setActionPending] = useState<"preview" | "confirm" | null>(null);
  const [refreshRevision, setRefreshRevision] = useState(0);
  const [editing, setEditing] = useState(false);

  const identityKey = datasetIdentity
    ? `${datasetIdentity.project_id}:${datasetIdentity.dataset_id}:${datasetIdentity.dataset_version_id}:${datasetIdentity.activation_revision ?? "current"}`
    : "unavailable";
  const selectedCatalog = useMemo(
    () => catalogs.find((catalog) => catalog.catalogVersionId === selectedCatalogVersionId) ?? null,
    [catalogs, selectedCatalogVersionId],
  );

  useEffect(() => {
    setSelectedCatalogVersionId("");
    setPreview(null);
    setAnalystRationale("");
    setEditing(false);
  }, [identityKey]);

  useEffect(() => {
    if (!shouldLoad) return;
    if (!enabled || !datasetIdentity || !projectId.trim()) {
      setLoadState("unavailable");
      setCatalogs([]);
      setBinding(null);
      setRequestError(null);
      return;
    }
    const controller = new AbortController();
    setLoadState("loading");
    setRequestError(null);
    void Promise.all([
      listEntitledBureauCatalogs({ signal: controller.signal }),
      getBureauMetadataBinding({
        projectId,
        datasetIdentity,
        signal: controller.signal,
      }),
    ])
      .then(([availableCatalogs, currentBinding]) => {
        if (controller.signal.aborted) return;
        setCatalogs(availableCatalogs);
        setBinding(currentBinding);
        setLoadState("ready");
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const safeError = error instanceof BureauMetadataRequestError
          ? error
          : new BureauMetadataRequestError({
              status: 0,
              code: "bureau_metadata_unavailable",
              kind: "unavailable",
              message: "Bureau metadata is currently unavailable.",
              recovery: "Retry after the service is available. No binding state was changed.",
            });
        setCatalogs([]);
        setBinding(null);
        setRequestError(safeError);
        setLoadState("unavailable");
      });
    return () => controller.abort();
  }, [datasetIdentity, enabled, identityKey, projectId, refreshRevision, shouldLoad]);

  function chooseCatalog(versionId: string) {
    setSelectedCatalogVersionId(versionId);
    setPreview(null);
    setAnalystRationale("");
    setRequestError(null);
  }

  async function preparePreview() {
    if (!datasetIdentity || !selectedCatalog || actionPending) return;
    setActionPending("preview");
    setRequestError(null);
    try {
      const result = await previewBureauMetadataBinding({
        projectId,
        datasetIdentity,
        catalog: selectedCatalog,
        expectedRevision: binding?.bindingRevision ?? 0,
      });
      setPreview(result);
    } catch (error) {
      setPreview(null);
      setRequestError(safeActionError(error));
    } finally {
      setActionPending(null);
    }
  }

  async function confirmPreview() {
    if (!datasetIdentity || !selectedCatalog || !preview || actionPending) return;
    setActionPending("confirm");
    setRequestError(null);
    try {
      const result = await confirmBureauMetadataBinding({
        projectId,
        datasetIdentity,
        catalog: selectedCatalog,
        preview,
        analystRationale,
      });
      setBinding(result);
      setPreview(null);
      setSelectedCatalogVersionId("");
      setAnalystRationale("");
      setEditing(false);
    } catch (error) {
      setRequestError(safeActionError(error));
    } finally {
      setActionPending(null);
    }
  }

  if (!shouldLoad) {
    return (
      <div className="flex justify-end" data-testid="bureau-metadata-binding-launcher" data-state="hidden">
        <button
          type="button"
          className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 hover:border-blue-300 hover:text-blue-700"
          aria-expanded="false"
          onClick={() => setExplicitlyOpened(true)}
        >
          <Database className="h-4 w-4" aria-hidden="true" />
          Review bureau metadata binding
        </button>
      </div>
    );
  }

  const showEditor = !binding || binding.stale || editing;
  const noCatalogEntitlement = loadState === "ready" && catalogs.length === 0;
  const rationaleReady = analystRationale.trim().length >= 8;
  // `current` describes an already-persisted exact binding, while `stale`
  // describes an existing different revision. Neither makes a freshly
  // prepared candidate invalid: the backend verifies the preview checksum and
  // optimistic revision again at confirmation time. Requiring either flag
  // here would deadlock first-time binding or a governed catalog change.
  const previewReady = Boolean(preview);

  return (
    <section
      className="scroll-mt-24 rounded-xl border border-blue-200 bg-white p-5 shadow-sm"
      data-testid="bureau-metadata-binding-panel"
      data-state={loadState}
      id="bureau-metadata-binding"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-[11px] font-bold uppercase tracking-wide text-blue-700">Governed metadata context</div>
          <h2 className="mt-1 flex items-center gap-2 text-base font-semibold text-slate-950">
            <Link2 className="h-4 w-4 text-blue-600" aria-hidden="true" />
            Bureau Metadata Binding
          </h2>
          <p className="mt-1 max-w-3xl text-sm leading-5 text-slate-600">
            Bind this exact Dataset Library version to one explicitly selected, entitled, checksum-verified bureau catalog version. Binding metadata does not choose special-value treatments or change downstream workflow state.
          </p>
        </div>
        {binding ? (
          <StatusBadge label="Binding" value={binding.stale ? "stale" : binding.current ? "current" : binding.status} />
        ) : null}
      </div>

      <div className="mt-4" aria-live="polite">
        {loadState === "loading" ? (
          <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-4 text-sm text-slate-700" data-testid="bureau-metadata-binding-loading">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            Loading the exact binding and entitled catalog inventory…
          </div>
        ) : null}

        {loadState === "unavailable" && !requestError ? (
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950" data-testid="bureau-metadata-binding-identity-unavailable">
            <div className="font-semibold">Exact dataset identity is required.</div>
            <p className="mt-1 text-xs leading-5">Select and activate a registered Dataset Library version before reviewing bureau metadata. No authoritative mapping has been created.</p>
          </div>
        ) : null}

        {requestError ? (
          <div className="rounded-lg border border-amber-300 bg-amber-50 p-4" data-testid="bureau-metadata-binding-unavailable">
            <div className="flex items-start gap-2 text-sm font-semibold text-amber-950">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              {requestError.message}
            </div>
            <p className="mt-1 text-xs leading-5 text-amber-900">{requestError.recovery}</p>
            <button
              type="button"
              className="mt-3 inline-flex items-center gap-2 rounded-lg border border-amber-400 bg-white px-3 py-2 text-xs font-semibold text-amber-900"
              onClick={() => setRefreshRevision((revision) => revision + 1)}
            >
              <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
              Retry exact binding
            </button>
          </div>
        ) : null}

        {noCatalogEntitlement && !requestError ? (
          <div className="rounded-lg border border-amber-300 bg-amber-50 p-4" data-testid="bureau-metadata-no-entitlement">
            <div className="flex items-start gap-2 text-sm font-semibold text-amber-950">
              <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              No entitled bureau catalog version is available.
            </div>
            <p className="mt-1 text-xs leading-5 text-amber-900">
              ATLAS has not created an authoritative mapping. Ask an administrator to verify the exact catalog entitlement; the existing Special-Value Review remains separate and unchanged.
            </p>
          </div>
        ) : null}

        {loadState === "ready" && binding ? <BindingSummary binding={binding} /> : null}

        {loadState === "ready" && binding && datasetIdentity ? (
          <BureauMetadataCrosswalkWorkspace
            projectId={projectId}
            datasetIdentity={datasetIdentity}
            bindingRevision={binding.bindingRevision}
            bindingCurrent={binding.current && !binding.stale}
            onBindingRevisionChanged={({ bindingRevision, crosswalkId, crosswalkRevision }) => {
              setBinding((current) => current ? {
                ...current,
                bindingRevision,
                crosswalkId,
                crosswalkRevision,
              } : current);
            }}
          />
        ) : null}

        {loadState === "ready" && !binding && catalogs.length > 0 ? (
          <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-800" data-testid="bureau-metadata-binding-unbound">
            <div className="font-semibold">No authoritative bureau metadata mapping exists for this exact dataset version.</div>
            <p className="mt-1 text-xs leading-5 text-slate-600">Choose one exact entitled catalog version explicitly to prepare a nonmutating preview.</p>
          </div>
        ) : null}
      </div>

      {loadState === "ready" && binding && !showEditor && catalogs.length > 0 ? (
        <div className="mt-4 flex justify-end">
          <button
            type="button"
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700 hover:border-blue-300 hover:text-blue-700"
            onClick={() => setEditing(true)}
          >
            Review a different exact version
          </button>
        </div>
      ) : null}

      {loadState === "ready" && showEditor && catalogs.length > 0 ? (
        <div className="mt-4 space-y-4 rounded-xl border border-slate-200 bg-slate-50 p-4" data-testid="bureau-metadata-binding-editor">
          <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
            <label className="block text-xs font-semibold text-slate-700">
              Exact entitled catalog version
              <select
                className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                value={selectedCatalogVersionId}
                onChange={(event) => chooseCatalog(event.target.value)}
                data-testid="bureau-metadata-catalog-select"
              >
                <option value="">Select an exact catalog version</option>
                {catalogs.map((catalog) => (
                  <option key={catalog.catalogVersionId} value={catalog.catalogVersionId}>
                    {catalogLabel(catalog)}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="inline-flex min-w-40 items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300"
              disabled={!selectedCatalog || actionPending !== null}
              onClick={() => void preparePreview()}
              data-testid="bureau-metadata-preview-button"
            >
              {actionPending === "preview" ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Eye className="h-4 w-4" aria-hidden="true" />}
              Preview exact binding
            </button>
          </div>
          {selectedCatalog ? (
            <div className="flex flex-wrap gap-2 text-xs">
              <StatusBadge label="Entitlement" value={selectedCatalog.entitlementState} />
              <StatusBadge label="Integrity" value={selectedCatalog.integrityState} />
              <StatusBadge label="Lifecycle" value={selectedCatalog.lifecycleState} />
              <span className="rounded-full border border-slate-200 bg-white px-2 py-1 font-semibold text-slate-700">
                {selectedCatalog.attributeCount.toLocaleString()} attributes · {selectedCatalog.specialDefinitionCount.toLocaleString()} special definitions
              </span>
            </div>
          ) : null}

          {preview && selectedCatalog ? (
            <>
              <PreviewSummary preview={preview} catalog={selectedCatalog} />
              <label className="block text-xs font-semibold text-slate-700">
                Analyst binding rationale
                <textarea
                  className="mt-1 min-h-20 w-full resize-y rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm leading-5 text-slate-950 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                  value={analystRationale}
                  maxLength={1000}
                  onChange={(event) => setAnalystRationale(event.target.value)}
                  placeholder="Explain why this exact catalog version applies to this exact dataset version."
                  data-testid="bureau-metadata-binding-rationale"
                />
                <span className="mt-1 block font-normal text-slate-500">Required for governed evidence; 8–1,000 characters.</span>
              </label>
              <div className="flex flex-wrap justify-end gap-2">
                <button
                  type="button"
                  className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700"
                  disabled={actionPending !== null}
                  onClick={() => {
                    setPreview(null);
                    setAnalystRationale("");
                  }}
                >
                  Discard preview
                </button>
                <button
                  type="button"
                  className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300"
                  disabled={!previewReady || !rationaleReady || actionPending !== null}
                  onClick={() => void confirmPreview()}
                  data-testid="bureau-metadata-confirm-button"
                >
                  {actionPending === "confirm" ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <ShieldCheck className="h-4 w-4" aria-hidden="true" />}
                  Confirm exact binding
                </button>
              </div>
            </>
          ) : null}
          {binding && editing ? (
            <div className="flex justify-end">
              <button
                type="button"
                className="text-xs font-semibold text-slate-600 hover:text-slate-950"
                onClick={() => {
                  setEditing(false);
                  setSelectedCatalogVersionId("");
                  setPreview(null);
                  setAnalystRationale("");
                }}
              >
                Keep current binding
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
