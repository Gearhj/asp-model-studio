import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type RefObject } from "react";
import {
  Archive,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Database,
  FileCheck2,
  KeyRound,
  LoaderCircle,
  RefreshCw,
  Search,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import {
  BUREAU_CATALOG_PAGE_SIZE,
  BureauCatalogAdminRequestError,
  checksumPrefix,
  getExactBureauCatalogAttribute,
  listEntitledBureauCatalogVersions,
  retireBureauCatalogVersion,
  searchBureauCatalogAttributes,
  validateBureauCatalogVersion,
  type BureauCatalogAttributeDetail,
  type BureauCatalogAttributePage,
  type BureauCatalogVersion,
} from "../lib/bureauCatalogAdmin";

type ViewError = {
  title: string;
  message: string;
  recovery: string;
  denied: boolean;
  retryable: boolean;
};

function viewError(error: unknown, title: string): ViewError {
  if (error instanceof BureauCatalogAdminRequestError) {
    return {
      title: error.denied ? "Administrative access required" : title,
      message: error.message,
      recovery: error.recovery,
      denied: error.denied,
      retryable: error.retryable,
    };
  }
  return {
    title,
    message: "The restricted bureau catalog service could not complete this request.",
    recovery: "Retry the request. No catalog state was changed by this response.",
    denied: false,
    retryable: true,
  };
}

export default function BureauCatalogAdmin() {
  const [catalogs, setCatalogs] = useState<BureauCatalogVersion[]>([]);
  const [selectedVersionId, setSelectedVersionId] = useState("");
  const [inventoryLoading, setInventoryLoading] = useState(true);
  const [inventoryError, setInventoryError] = useState<ViewError | null>(null);
  const [actionError, setActionError] = useState<ViewError | null>(null);
  const [notice, setNotice] = useState("");
  const [operation, setOperation] = useState<"validate" | "retire" | null>(null);
  const [retireConfirmation, setRetireConfirmation] = useState(false);

  const [queryDraft, setQueryDraft] = useState("");
  const [query, setQuery] = useState("");
  const [attributePage, setAttributePage] = useState<BureauCatalogAttributePage | null>(null);
  const [attributesLoading, setAttributesLoading] = useState(false);
  const [attributesError, setAttributesError] = useState<ViewError | null>(null);

  const [exactCode, setExactCode] = useState("");
  const [exactAttribute, setExactAttribute] = useState<BureauCatalogAttributeDetail | null>(null);
  const [exactLoading, setExactLoading] = useState(false);
  const [exactError, setExactError] = useState<ViewError | null>(null);
  const confirmRetireRef = useRef<HTMLButtonElement>(null);

  const selectedCatalog = useMemo(
    () => catalogs.find((catalog) => catalog.versionId === selectedVersionId) ?? null,
    [catalogs, selectedVersionId],
  );

  const refreshInventory = useCallback(async (preferredVersionId?: string) => {
    setInventoryLoading(true);
    setInventoryError(null);
    try {
      const nextCatalogs = await listEntitledBureauCatalogVersions();
      setCatalogs(nextCatalogs);
      setSelectedVersionId((current) => {
        if (
          preferredVersionId
          && nextCatalogs.some((catalog) => catalog.versionId === preferredVersionId)
        ) {
          return preferredVersionId;
        }
        if (current && nextCatalogs.some((catalog) => catalog.versionId === current)) {
          return current;
        }
        return "";
      });
    } catch (error) {
      setCatalogs([]);
      setSelectedVersionId("");
      setInventoryError(viewError(error, "Catalog inventory unavailable"));
    } finally {
      setInventoryLoading(false);
    }
  }, []);

  const loadAttributes = useCallback(async (versionId: string, nextQuery: string, offset: number) => {
    if (!versionId) return;
    setAttributesLoading(true);
    setAttributesError(null);
    try {
      setAttributePage(
        await searchBureauCatalogAttributes({
          versionId,
          query: nextQuery,
          offset,
          limit: BUREAU_CATALOG_PAGE_SIZE,
        }),
      );
    } catch (error) {
      setAttributePage(null);
      setAttributesError(viewError(error, "Attribute search unavailable"));
    } finally {
      setAttributesLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshInventory();
  }, [refreshInventory]);

  useEffect(() => {
    setQueryDraft("");
    setQuery("");
    setAttributePage(null);
    setAttributesError(null);
    setExactCode("");
    setExactAttribute(null);
    setExactError(null);
    setRetireConfirmation(false);
  }, [selectedVersionId]);

  useEffect(() => {
    if (retireConfirmation) confirmRetireRef.current?.focus();
  }, [retireConfirmation]);

  async function runValidation() {
    if (!selectedCatalog) return;
    setOperation("validate");
    setActionError(null);
    setNotice("");
    try {
      await validateBureauCatalogVersion(selectedCatalog.versionId);
      await refreshInventory(selectedCatalog.versionId);
      setNotice(`Validation completed for exact version ${selectedCatalog.dictionaryVersion}.`);
    } catch (error) {
      setActionError(viewError(error, "Catalog validation failed"));
    } finally {
      setOperation(null);
    }
  }

  async function runRetirement() {
    if (!selectedCatalog) return;
    setOperation("retire");
    setActionError(null);
    setNotice("");
    try {
      await retireBureauCatalogVersion(selectedCatalog.versionId);
      setRetireConfirmation(false);
      await refreshInventory(selectedCatalog.versionId);
      setNotice(`Exact version ${selectedCatalog.dictionaryVersion} is retired from new use.`);
    } catch (error) {
      setActionError(viewError(error, "Catalog retirement failed"));
    } finally {
      setOperation(null);
    }
  }

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    const nextQuery = queryDraft.trim();
    setQuery(nextQuery);
    if (selectedVersionId) void loadAttributes(selectedVersionId, nextQuery, 0);
  }

  async function submitExactLookup(event: FormEvent) {
    event.preventDefault();
    if (!selectedVersionId) return;
    setExactLoading(true);
    setExactError(null);
    setExactAttribute(null);
    try {
      setExactAttribute(await getExactBureauCatalogAttribute(selectedVersionId, exactCode));
    } catch (error) {
      setExactError(viewError(error, "Exact attribute lookup failed"));
    } finally {
      setExactLoading(false);
    }
  }

  function inspectExactAttribute(code: string) {
    setExactCode(code);
    setExactLoading(true);
    setExactError(null);
    setExactAttribute(null);
    void getExactBureauCatalogAttribute(selectedVersionId, code)
      .then(setExactAttribute)
      .catch((error) => setExactError(viewError(error, "Exact attribute lookup failed")))
      .finally(() => setExactLoading(false));
  }

  return (
    <main className="atlas-page-shell space-y-5" data-testid="bureau-catalog-admin">
      <section className="overflow-hidden rounded-2xl border border-slate-900 bg-gradient-to-br from-slate-950 via-slate-900 to-blue-950 p-5 text-white shadow-sm sm:p-6">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-sky-200">
              <ShieldCheck size={16} aria-hidden="true" />
              Restricted platform administration
            </div>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">Bureau Catalog Administration</h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-300">
              Review installed provider-neutral dictionary versions, verify integrity, and inspect bounded attribute records. Catalog content remains entitlement-gated and cannot be exported from this workspace.
            </p>
            <p className="mt-2 max-w-3xl text-xs leading-5 text-slate-400" data-testid="bureau-catalog-context-safety">
              Requests use the current authenticated administrator and tenant context. This page does not change the active modeling project or dataset identity.
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-sky-400/40 bg-sky-400/10 px-3 py-1.5 text-xs font-semibold text-sky-100">
              <KeyRound size={14} aria-hidden="true" /> Administration only
            </span>
            <button
              type="button"
              onClick={() => void refreshInventory(selectedVersionId)}
              disabled={inventoryLoading}
              className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-white/25 bg-white/10 px-3 py-2 text-sm font-semibold text-white transition hover:bg-white/15 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-300 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <RefreshCw size={16} className={inventoryLoading ? "animate-spin" : ""} aria-hidden="true" />
              Refresh inventory
            </button>
          </div>
        </div>
      </section>

      {inventoryLoading && !catalogs.length ? (
        <LoadingPanel label="Loading entitled catalog versions" />
      ) : inventoryError ? (
        <ErrorPanel error={inventoryError} onRetry={() => void refreshInventory()} />
      ) : !catalogs.length ? (
        <EmptyPanel />
      ) : (
        <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(250px,0.32fr)_minmax(0,1fr)]">
          <CatalogVersionList
            catalogs={catalogs}
            selectedVersionId={selectedVersionId}
            onSelect={setSelectedVersionId}
          />

          {selectedCatalog ? (
            <div className="min-w-0 space-y-5">
              <CatalogOverview
                catalog={selectedCatalog}
                operation={operation}
                retireConfirmation={retireConfirmation}
                confirmRetireRef={confirmRetireRef}
                onValidate={() => void runValidation()}
                onRequestRetire={() => setRetireConfirmation(true)}
                onConfirmRetire={() => void runRetirement()}
                onCancelRetire={() => setRetireConfirmation(false)}
              />

              <div aria-live="polite" aria-atomic="true">
                {notice ? (
                  <div className="flex items-start gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900" role="status">
                    <CheckCircle2 size={17} className="mt-0.5 shrink-0" aria-hidden="true" />
                    {notice}
                  </div>
                ) : null}
              </div>
              {actionError ? <InlineError error={actionError} /> : null}

              <AttributeSearchWorkspace
                queryDraft={queryDraft}
                query={query}
                onQueryDraftChange={setQueryDraft}
                onSubmit={submitSearch}
                page={attributePage}
                loading={attributesLoading}
                error={attributesError}
                onPrevious={() => {
                  if (!attributePage) return;
                  void loadAttributes(selectedVersionId, query, Math.max(0, attributePage.offset - attributePage.limit));
                }}
                onNext={() => {
                  if (!attributePage) return;
                  void loadAttributes(selectedVersionId, query, attributePage.offset + attributePage.limit);
                }}
                onRetry={() => void loadAttributes(selectedVersionId, query, attributePage?.offset ?? 0)}
                onInspect={inspectExactAttribute}
              />

              <ExactLookupWorkspace
                catalog={selectedCatalog}
                exactCode={exactCode}
                onExactCodeChange={setExactCode}
                onSubmit={submitExactLookup}
                loading={exactLoading}
                error={exactError}
                attribute={exactAttribute}
              />
            </div>
          ) : (
            <CatalogSelectionRequired />
          )}
        </div>
      )}
    </main>
  );
}

function CatalogSelectionRequired() {
  return (
    <section
      className="flex min-h-64 items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-white p-6 text-center shadow-sm"
      data-testid="bureau-catalog-selection-required"
      aria-labelledby="catalog-selection-required-title"
    >
      <div className="max-w-lg">
        <Database size={28} className="mx-auto text-slate-400" aria-hidden="true" />
        <h2 id="catalog-selection-required-title" className="mt-3 text-base font-semibold text-slate-950">
          Select an exact catalog version
        </h2>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          Choose one entitled version from the inventory before ATLAS loads any restricted catalog details. No first or latest version is selected automatically.
        </p>
      </div>
    </section>
  );
}

function CatalogVersionList({
  catalogs,
  selectedVersionId,
  onSelect,
}: {
  catalogs: BureauCatalogVersion[];
  selectedVersionId: string;
  onSelect: (versionId: string) => void;
}) {
  return (
    <aside className="h-fit rounded-2xl border border-slate-200 bg-white p-4 shadow-sm xl:sticky xl:top-4" aria-label="Installed bureau catalog versions">
      <div className="flex items-center gap-2">
        <Database size={17} className="text-blue-700" aria-hidden="true" />
        <h2 className="text-sm font-semibold text-slate-950">Installed versions</h2>
      </div>
      <p className="mt-2 text-xs leading-5 text-slate-600">Server-filtered entitled versions only. Select an exact version; ATLAS never substitutes a first or latest dictionary.</p>
      <ul className="mt-4 grid gap-2">
        {catalogs.map((catalog) => {
          const selected = catalog.versionId === selectedVersionId;
          return (
            <li key={catalog.versionId}>
              <button
                type="button"
                aria-pressed={selected}
                onClick={() => onSelect(catalog.versionId)}
                className={`w-full rounded-xl border px-3 py-3 text-left transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 ${
                  selected
                    ? "border-blue-500 bg-blue-50 shadow-sm"
                    : "border-slate-200 bg-white hover:border-blue-300 hover:bg-slate-50"
                }`}
              >
                <span className="block truncate text-sm font-semibold text-slate-950">{catalog.provider} / {catalog.product}</span>
                <span className="mt-1 block text-xs text-slate-600">{catalog.edition} / {catalog.dictionaryVersion}</span>
                <span className="mt-2 flex flex-wrap gap-1.5">
                  <StatusBadge status={catalog.lifecycleStatus} />
                  <StatusBadge status={catalog.integrityStatus} />
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}

function CatalogOverview({
  catalog,
  operation,
  retireConfirmation,
  confirmRetireRef,
  onValidate,
  onRequestRetire,
  onConfirmRetire,
  onCancelRetire,
}: {
  catalog: BureauCatalogVersion;
  operation: "validate" | "retire" | null;
  retireConfirmation: boolean;
  confirmRetireRef: RefObject<HTMLButtonElement>;
  onValidate: () => void;
  onRequestRetire: () => void;
  onConfirmRetire: () => void;
  onCancelRetire: () => void;
}) {
  const retired = catalog.lifecycleStatus.toLowerCase() === "retired";
  const busy = operation !== null;
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5" aria-labelledby="catalog-overview-title" aria-busy={busy}>
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="text-xs font-semibold uppercase tracking-[0.12em] text-blue-700">Exact installed version</div>
          <h2 id="catalog-overview-title" className="mt-1 break-words text-xl font-semibold text-slate-950">
            {catalog.provider} {catalog.product} / {catalog.edition} / {catalog.dictionaryVersion}
          </h2>
          <p className="mt-1 text-xs text-slate-500">Version ID: <code className="break-all font-mono text-slate-700">{catalog.versionId}</code></p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onValidate}
            disabled={busy || retired}
            className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            {operation === "validate" ? <LoaderCircle size={16} className="animate-spin" aria-hidden="true" /> : <FileCheck2 size={16} aria-hidden="true" />}
            Validate integrity
          </button>
          <button
            type="button"
            onClick={onRequestRetire}
            disabled={busy || retired || retireConfirmation}
            className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm font-semibold text-amber-900 transition hover:bg-amber-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-600 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Archive size={16} aria-hidden="true" />
            {retired ? "Version retired" : "Retire version"}
          </button>
        </div>
      </div>

      <dl className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetadataCell label="Catalog ID" value={catalog.catalogId || "Not recorded"} mono />
        <MetadataCell label="Checksum prefix" value={checksumPrefix(catalog.catalogChecksum)} mono />
        <MetadataCell label="Attributes" value={catalog.attributeCount.toLocaleString()} />
        <MetadataCell label="Special values" value={catalog.specialValueCount.toLocaleString()} />
      </dl>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Catalog control status">
        <StatusCell label="Integrity" status={catalog.integrityStatus} />
        <StatusCell label="Installation" status={catalog.installStatus} />
        <StatusCell label="Entitlement" status={catalog.entitlementStatus} />
        <StatusCell label="Validation" status={catalog.validationStatus} />
      </div>

      {retireConfirmation ? (
        <div className="mt-4 rounded-xl border border-amber-300 bg-amber-50 p-4" role="alert" aria-labelledby="retire-confirmation-title">
          <div className="flex items-start gap-3">
            <TriangleAlert size={19} className="mt-0.5 shrink-0 text-amber-700" aria-hidden="true" />
            <div>
              <h3 id="retire-confirmation-title" className="text-sm font-semibold text-amber-950">Confirm catalog retirement</h3>
              <p className="mt-1 text-sm leading-5 text-amber-900">Retirement prevents new use of this exact version. It does not delete the catalog or rewrite existing governed lineage.</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  ref={confirmRetireRef}
                  type="button"
                  onClick={onConfirmRetire}
                  disabled={busy}
                  className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-amber-700 px-3 py-2 text-sm font-semibold text-white hover:bg-amber-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-700 disabled:opacity-60"
                >
                  {operation === "retire" ? <LoaderCircle size={16} className="animate-spin" aria-hidden="true" /> : <Archive size={16} aria-hidden="true" />}
                  Confirm retirement
                </button>
                <button
                  type="button"
                  onClick={onCancelRetire}
                  disabled={busy}
                  className="min-h-10 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-600 disabled:opacity-60"
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function AttributeSearchWorkspace({
  queryDraft,
  query,
  onQueryDraftChange,
  onSubmit,
  page,
  loading,
  error,
  onPrevious,
  onNext,
  onRetry,
  onInspect,
}: {
  queryDraft: string;
  query: string;
  onQueryDraftChange: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
  page: BureauCatalogAttributePage | null;
  loading: boolean;
  error: ViewError | null;
  onPrevious: () => void;
  onNext: () => void;
  onRetry: () => void;
  onInspect: (code: string) => void;
}) {
  const first = page?.attributes.length ? page.offset + 1 : 0;
  const last = page
    ? page.total !== undefined
      ? Math.min(page.total, page.offset + page.attributes.length)
      : page.offset + page.attributes.length
    : 0;
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5" aria-labelledby="attribute-search-title" aria-busy={loading}>
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.12em] text-blue-700">Bounded catalog access</div>
          <h2 id="attribute-search-title" className="mt-1 text-lg font-semibold text-slate-950">Attribute search</h2>
          <p className="mt-1 max-w-2xl text-sm leading-5 text-slate-600">Search one exact version in pages of {BUREAU_CATALOG_PAGE_SIZE}. Bulk export, download, and copy-all actions are not available.</p>
        </div>
        <form onSubmit={onSubmit} className="flex w-full min-w-0 flex-col gap-2 sm:flex-row lg:max-w-xl" role="search">
          <label className="min-w-0 flex-1 text-xs font-semibold text-slate-700">
            Search attribute code or label
            <input
              type="search"
              value={queryDraft}
              onChange={(event) => onQueryDraftChange(event.target.value)}
              maxLength={120}
              className="mt-1 min-h-10 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950 shadow-sm placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200"
              placeholder="Enter a code or term"
            />
          </label>
          <button
            type="submit"
            disabled={loading || !queryDraft.trim()}
            className="inline-flex min-h-10 items-center justify-center gap-2 self-end rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            <Search size={16} aria-hidden="true" /> Search
          </button>
        </form>
      </div>

      <div className="mt-4" aria-live="polite" aria-atomic="true">
        {loading ? <LoadingInline label="Loading bounded attribute results" /> : null}
      </div>
      {error ? <InlineError error={error} onRetry={onRetry} /> : null}

      {!loading && !error && page ? (
        <>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-600">
            <span role="status" aria-live="polite">Showing {first.toLocaleString()}-{last.toLocaleString()}{page.total !== undefined ? ` of ${page.total.toLocaleString()}` : page.hasNext ? "; more results available" : ""}{query ? ` for "${query}"` : ""}</span>
            <span>Limit {page.limit.toLocaleString()} records</span>
          </div>
          <div className="mt-3 overflow-x-auto rounded-xl border border-slate-200">
            <table className="w-full min-w-[820px] text-left text-sm">
              <thead className="bg-slate-100 text-[11px] font-semibold uppercase tracking-wide text-slate-600">
                <tr>
                  <th scope="col" className="px-3 py-2">Attribute code</th>
                  <th scope="col" className="px-3 py-2">Label</th>
                  <th scope="col" className="px-3 py-2">Units</th>
                  <th scope="col" className="px-3 py-2">Ordinary range</th>
                  <th scope="col" className="px-3 py-2 text-right">Special values</th>
                  <th scope="col" className="px-3 py-2">Review</th>
                  <th scope="col" className="px-3 py-2"><span className="sr-only">Exact record action</span></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {page.attributes.map((attribute) => (
                  <tr key={attribute.attributeCode} className="odd:bg-white even:bg-slate-50/70">
                    <th scope="row" className="px-3 py-3 font-mono text-xs font-semibold text-slate-950">{attribute.attributeCode}</th>
                    <td className="max-w-sm px-3 py-3">
                      <div className="font-medium text-slate-900">{attribute.displayName || "No safe label recorded"}</div>
                      {attribute.description ? <div className="mt-1 line-clamp-2 text-xs leading-4 text-slate-500">{attribute.description}</div> : null}
                    </td>
                    <td className="px-3 py-3 text-slate-700">{attribute.units || "-"}</td>
                    <td className="px-3 py-3 font-mono text-xs text-slate-700">{formatRange(attribute.ordinaryValidMin, attribute.ordinaryValidMax, attribute.validRangeExpression)}</td>
                    <td className="px-3 py-3 text-right tabular-nums text-slate-700">{attribute.specialValueCount?.toLocaleString() ?? "-"}</td>
                    <td className="px-3 py-3"><StatusBadge status={attribute.reviewStatus} /></td>
                    <td className="px-3 py-3 text-right">
                      <button
                        type="button"
                        onClick={() => onInspect(attribute.attributeCode)}
                        className="min-h-9 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:border-blue-400 hover:text-blue-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
                        aria-label={`Inspect exact attribute ${attribute.attributeCode}`}
                      >
                        Inspect exact
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!page.attributes.length ? (
            <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-8 text-center text-sm text-slate-600">No attributes matched this bounded search.</div>
          ) : null}
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <button
              type="button"
              onClick={onPrevious}
              disabled={loading || page.offset === 0}
              className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <ChevronLeft size={16} aria-hidden="true" /> Previous page
            </button>
            <span className="text-xs font-medium text-slate-600">Offset {page.offset.toLocaleString()}</span>
            <button
              type="button"
              onClick={onNext}
              disabled={loading || !page.hasNext}
              className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Next page <ChevronRight size={16} aria-hidden="true" />
            </button>
          </div>
        </>
      ) : null}
      {!loading && !error && !page ? (
        <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-8 text-center text-sm leading-6 text-slate-600">Enter a code or term to start a bounded, entitlement-checked search. Unfiltered catalog browsing is disabled.</div>
      ) : null}
    </section>
  );
}

function ExactLookupWorkspace({
  catalog,
  exactCode,
  onExactCodeChange,
  onSubmit,
  loading,
  error,
  attribute,
}: {
  catalog: BureauCatalogVersion;
  exactCode: string;
  onExactCodeChange: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
  loading: boolean;
  error: ViewError | null;
  attribute: BureauCatalogAttributeDetail | null;
}) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5" aria-labelledby="exact-lookup-title" aria-busy={loading}>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,0.42fr)_minmax(0,0.58fr)]">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.12em] text-blue-700">Single-record access</div>
          <h2 id="exact-lookup-title" className="mt-1 text-lg font-semibold text-slate-950">Exact attribute lookup</h2>
          <p className="mt-1 text-sm leading-5 text-slate-600">Enter the complete attribute code. Similar-code and latest-version fallback are prohibited.</p>
          <form onSubmit={onSubmit} className="mt-4 grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]">
            <label className="text-xs font-semibold text-slate-700">
              Exact attribute code
              <input
                value={exactCode}
                onChange={(event) => onExactCodeChange(event.target.value)}
                maxLength={128}
                autoComplete="off"
                spellCheck={false}
                className="mt-1 min-h-10 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 font-mono text-sm text-slate-950 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200"
                placeholder="Exact code"
              />
            </label>
            <button
              type="submit"
              disabled={loading || !exactCode.trim()}
              className="inline-flex min-h-10 items-center justify-center gap-2 self-end rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              {loading ? <LoaderCircle size={16} className="animate-spin" aria-hidden="true" /> : <Search size={16} aria-hidden="true" />}
              Look up exact
            </button>
          </form>
          <p className="mt-2 text-xs leading-5 text-slate-500">Results are limited to one entitled attribute record. There is no bulk copy or export action.</p>
          <div className="mt-3" aria-live="polite">{loading ? <LoadingInline label="Loading exact attribute record" /> : null}</div>
          {error ? <InlineError error={error} /> : null}
        </div>

        <div className="min-w-0 rounded-xl border border-slate-200 bg-slate-50 p-4" data-testid="exact-attribute-result">
          {attribute ? (
            <div>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="font-mono text-sm font-semibold text-slate-950">{attribute.attributeCode}</div>
                  <div className="mt-1 text-sm font-semibold text-slate-800">{attribute.displayName || "No safe label recorded"}</div>
                </div>
                <StatusBadge status={attribute.reconciliationStatus} />
              </div>
              {attribute.description ? <p className="mt-3 text-sm leading-6 text-slate-700">{attribute.description}</p> : null}
              <dl className="mt-4 grid gap-3 sm:grid-cols-2">
                <Detail label="Dictionary" value={[catalog.provider, catalog.product, catalog.edition, catalog.dictionaryVersion].filter(Boolean).join(" / ")} />
                <Detail label="Ordinary range" value={formatRange(attribute.ordinaryValidMin, attribute.ordinaryValidMax, attribute.validRangeExpression)} />
                <Detail label="Units" value={attribute.units || "Not recorded"} />
                <Detail label="Numeric type" value={attribute.numericType || "Not recorded"} />
                <Detail label="Valid-value expression" value={attribute.validValueExpression || "Not recorded"} />
                <Detail label="Special-value definitions" value={attribute.specialValueCount?.toLocaleString() ?? "Not returned by this exact record"} />
                <Detail label="Cross-bureau availability" value={attribute.crossBureauAvailability.length ? attribute.crossBureauAvailability.join(", ") : "Not recorded"} />
                <Detail label="Source provenance" value={attribute.sourcePage ? `Verified source page ${attribute.sourcePage}` : "Source page not recorded"} />
              </dl>
            </div>
          ) : (
            <div className="flex min-h-52 items-center justify-center text-center text-sm leading-6 text-slate-500">Select a search result or enter an exact code to inspect one restricted record.</div>
          )}
        </div>
      </div>
    </section>
  );
}

function ErrorPanel({ error, onRetry }: { error: ViewError; onRetry: () => void }) {
  return (
    <section className="rounded-2xl border border-red-200 bg-red-50 p-5 text-red-950 shadow-sm" role="alert" aria-labelledby="catalog-error-title">
      <div className="flex items-start gap-3">
        <TriangleAlert size={21} className="mt-0.5 shrink-0 text-red-700" aria-hidden="true" />
        <div>
          <h2 id="catalog-error-title" className="font-semibold">{error.title}</h2>
          <p className="mt-1 text-sm leading-6">{error.message}</p>
          <p className="mt-2 text-sm leading-6 text-red-800">{error.recovery}</p>
          <button
            type="button"
            onClick={onRetry}
            className="mt-4 inline-flex min-h-10 items-center gap-2 rounded-lg border border-red-300 bg-white px-3 py-2 text-sm font-semibold text-red-900 hover:bg-red-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-700"
          >
            <RefreshCw size={16} aria-hidden="true" /> {error.denied ? "Retry authorization check" : "Retry catalog request"}
          </button>
        </div>
      </div>
    </section>
  );
}

function InlineError({ error, onRetry }: { error: ViewError; onRetry?: () => void }) {
  return (
    <div className="mt-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-950" role="alert">
      <div className="font-semibold">{error.title}</div>
      <div className="mt-1 leading-5">{error.message}</div>
      <div className="mt-1 text-red-800">{error.recovery}</div>
      {onRetry && error.retryable ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 min-h-9 rounded-lg border border-red-300 bg-white px-3 py-1.5 text-xs font-semibold text-red-900 hover:bg-red-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-700"
        >
          Retry
        </button>
      ) : null}
    </div>
  );
}

function LoadingPanel({ label }: { label: string }) {
  return (
    <section className="flex min-h-48 items-center justify-center rounded-2xl border border-slate-200 bg-white p-6 text-sm text-slate-600 shadow-sm" role="status" aria-live="polite">
      <LoaderCircle size={19} className="mr-2 animate-spin text-blue-700" aria-hidden="true" /> {label}
    </section>
  );
}

function LoadingInline({ label }: { label: string }) {
  return <div className="inline-flex items-center gap-2 text-sm text-slate-600" role="status"><LoaderCircle size={16} className="animate-spin text-blue-700" aria-hidden="true" /> {label}</div>;
}

function EmptyPanel() {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-sm" data-testid="bureau-catalog-empty-state">
      <Database size={28} className="mx-auto text-slate-400" aria-hidden="true" />
      <h2 className="mt-3 text-base font-semibold text-slate-950">No entitled catalog versions</h2>
      <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-slate-600">No installed bureau catalog version is available to this administrator. ATLAS will not discover or substitute an unentitled version.</p>
    </section>
  );
}

function MetadataCell({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return <div className="min-w-0 rounded-xl border border-slate-200 bg-slate-50 px-3 py-3"><dt className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</dt><dd className={`mt-1 break-all text-sm font-semibold text-slate-900 ${mono ? "font-mono text-xs" : ""}`}>{value}</dd></div>;
}

function StatusCell({ label, status }: { label: string; status: string }) {
  return <div className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white px-3 py-3"><span className="text-xs font-semibold text-slate-600">{label}</span><StatusBadge status={status} /></div>;
}

function StatusBadge({ status }: { status: string }) {
  const normalized = (status || "unknown").trim().toLowerCase();
  const positive = ["active", "installed", "verified", "valid", "passed", "entitled", "approved", "complete", "current"].some((value) => normalized.includes(value));
  const warning = ["warning", "pending", "review", "unknown", "unverified"].some((value) => normalized.includes(value));
  const classes = positive
    ? "bg-emerald-100 text-emerald-800"
    : warning
      ? "bg-amber-100 text-amber-800"
      : "bg-slate-200 text-slate-700";
  return <span className={`inline-flex max-w-full rounded-full px-2 py-1 text-[11px] font-semibold ${classes}`}><span className="truncate">{status || "unknown"}</span></span>;
}

function Detail({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0"><dt className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</dt><dd className="mt-1 break-words text-sm leading-5 text-slate-800">{value}</dd></div>;
}

function formatRange(minimum?: string, maximum?: string, expression?: string) {
  if (minimum && maximum) return `${minimum} to ${maximum}`;
  if (minimum) return `At least ${minimum}`;
  if (maximum) return `At most ${maximum}`;
  if (expression) return expression;
  return "Not recorded";
}
