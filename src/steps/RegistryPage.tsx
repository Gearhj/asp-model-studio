import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Database, FilterX, FolderOpen, RefreshCw, Search, ShieldCheck } from "lucide-react";
import AtlasCard from "../components/ui/AtlasCard";
import AtlasEmptyState from "../components/ui/AtlasEmptyState";
import AtlasPageHero from "../components/ui/AtlasPageHero";
import AtlasProgressBar from "../components/ui/AtlasProgressBar";
import { ASSET_TYPE_LABELS, RegistryStatus, TEMPLATE_LABELS, formatRegistryDate, humanize } from "../components/registry/RegistryPrimitives";
import { getRegistryAssets, getRegistryOwners, type RegistryAsset, type RegistryFilters, type RegistryOwner } from "../lib/registryApi";

const LIFECYCLE_OPTIONS = ["Draft", "Development", "Ready for Review", "Validation", "Recommended", "Approved", "Implementation Planned", "Implemented", "Monitoring", "Returned", "Rejected", "Retired"];
const READINESS_OPTIONS = ["Ready", "Approved", "Complete", "Incomplete", "Pending", "Not started", "Missing", "Stale", "Rejected"];

type Filters = {
  search: string;
  asset_type: string;
  workflow_type: string;
  lifecycle_status: string;
  owner_user_id: string;
  evidence_status: string;
  documentation_status: string;
  validation_status: string;
};

const EMPTY_FILTERS: Filters = {
  search: "",
  asset_type: "",
  workflow_type: "",
  lifecycle_status: "",
  owner_user_id: "",
  evidence_status: "",
  documentation_status: "",
  validation_status: "",
};

export default function RegistryPage() {
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [assets, setAssets] = useState<RegistryAsset[]>([]);
  const [owners, setOwners] = useState<RegistryOwner[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async (activeFilters: Filters = filters) => {
    setLoading(true);
    setError("");
    try {
      const query = Object.fromEntries(Object.entries(activeFilters).filter(([, value]) => value)) as RegistryFilters;
      const [assetPayload, ownerPayload] = await Promise.all([
        getRegistryAssets({ ...query, limit: 500 }),
        getRegistryOwners(),
      ]);
      setAssets(assetPayload.assets);
      setTotal(assetPayload.total);
      setOwners(ownerPayload.owners);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "ATLAS could not load the registry.");
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(filters), filters.search ? 280 : 0);
    return () => window.clearTimeout(timer);
  }, [filters, load]);

  const workflowOptions = useMemo(() => [...new Set(assets.map((asset) => asset.workflow_type).filter(Boolean))].sort(), [assets]);
  const activeFilterCount = Object.values(filters).filter(Boolean).length;

  const update = (field: keyof Filters, value: string) => setFilters((current) => ({ ...current, [field]: value }));
  const clearFilters = () => setFilters(EMPTY_FILTERS);

  return (
    <div className="atlas-page-shell atlas-theme-analytics" data-testid="registry-page">
      <AtlasPageHero
        dark
        eyebrow="Governed analytical asset inventory"
        title="Model / Decision Registry"
        subtitle="Search, assess, and open the persisted models, optimization studies, experiments, tests, and decision strategies managed by ATLAS."
        actions={(
          <>
            <Link to="/management-dashboard" className="atlas-secondary-button border-white/30 bg-white/10 text-white hover:bg-white/20">Management Dashboard</Link>
            <button type="button" className="atlas-secondary-button border-white/30 bg-white/10 text-white hover:bg-white/20" onClick={() => void load()} disabled={loading}>
              <RefreshCw size={16} className={loading ? "animate-spin" : ""} /> Refresh registry
            </button>
          </>
        )}
        aside={(
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-white/20 bg-white/15">
            <HeroFact label="Matching assets" value={total} />
            <HeroFact label="Active filters" value={activeFilterCount} />
            <HeroFact label="Source" value="SQLite registry" />
            <HeroFact label="Status" value={loading ? "Refreshing" : error ? "Unavailable" : "Current"} />
          </div>
        )}
      />

      <AtlasCard eyebrow="Registry controls" title="Filter governed assets" action={activeFilterCount ? <button type="button" onClick={clearFilters} className="atlas-tertiary-button"><FilterX size={15} /> Clear {activeFilterCount}</button> : undefined}>
        <div className="grid gap-3 lg:grid-cols-4 2xl:grid-cols-8">
          <label className="relative lg:col-span-2 2xl:col-span-2">
            <span className="atlas-eyebrow">Search</span>
            <Search size={16} className="pointer-events-none absolute bottom-2.5 left-3 text-slate-400" />
            <input className="atlas-input mt-1 pl-9" value={filters.search} onChange={(event) => update("search", event.target.value)} placeholder="Name, owner, purpose, tag..." />
          </label>
          <FilterSelect label="Asset type" value={filters.asset_type} onChange={(value) => update("asset_type", value)} options={Object.entries(ASSET_TYPE_LABELS)} />
          <FilterSelect label="Workflow" value={filters.workflow_type} onChange={(value) => update("workflow_type", value)} options={workflowOptions.map((value) => [value, humanize(value)])} />
          <FilterSelect label="Lifecycle" value={filters.lifecycle_status} onChange={(value) => update("lifecycle_status", value)} options={LIFECYCLE_OPTIONS.map((value) => [value, value])} />
          <FilterSelect label="Owner" value={filters.owner_user_id} onChange={(value) => update("owner_user_id", value)} options={owners.map((owner) => [owner.user_id, owner.display_name])} />
          <FilterSelect label="Evidence" value={filters.evidence_status} onChange={(value) => update("evidence_status", value)} options={READINESS_OPTIONS.map((value) => [value, value])} />
          <FilterSelect label="Documentation" value={filters.documentation_status} onChange={(value) => update("documentation_status", value)} options={READINESS_OPTIONS.map((value) => [value, value])} />
          <FilterSelect label="Validation" value={filters.validation_status} onChange={(value) => update("validation_status", value)} options={READINESS_OPTIONS.map((value) => [value, value])} />
        </div>
      </AtlasCard>

      {error && (
        <AtlasCard tone="attention" title="Registry unavailable">
          <p className="text-sm leading-6">{error}</p>
          <button type="button" className="atlas-secondary-button mt-4" onClick={() => void load()}>Try again</button>
        </AtlasCard>
      )}

      <AtlasCard
        eyebrow="Portfolio inventory"
        title={`${total} governed asset${total === 1 ? "" : "s"}`}
        action={<span className="inline-flex items-center gap-2 text-xs font-semibold text-slate-500"><Database size={14} /> Persisted records only</span>}
      >
        {loading && !assets.length ? <RegistryLoading /> : assets.length ? (
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="min-w-[1960px] w-full border-collapse text-left text-sm" aria-label="Model and decision registry">
              <thead className="sticky top-0 bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-3">Name</th><th className="px-4 py-3">Type</th><th className="px-4 py-3">Workflow / Template</th><th className="px-4 py-3">Owner</th><th className="px-4 py-3">Lifecycle</th><th className="px-4 py-3 min-w-44">Evidence</th><th className="px-4 py-3 min-w-44">Documentation</th><th className="px-4 py-3">Validation</th><th className="px-4 py-3">Recommendation</th><th className="px-4 py-3">Implementation</th><th className="px-4 py-3">Monitoring</th><th className="px-4 py-3">Open alerts</th><th className="px-4 py-3">Last monitoring run</th><th className="px-4 py-3">Next monitoring due</th><th className="px-4 py-3">Last activity</th><th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {assets.map((asset) => <RegistryRow key={asset.project_id} asset={asset} />)}
              </tbody>
            </table>
          </div>
        ) : !loading ? (
          <AtlasEmptyState
            title={activeFilterCount ? "No assets match these filters" : "No persisted analytical assets"}
            body={activeFilterCount ? "Clear one or more filters to broaden the registry view." : "Create or restore an ATLAS project to register the first governed analytical asset."}
            action={activeFilterCount ? <button type="button" className="atlas-secondary-button" onClick={clearFilters}>Clear filters</button> : <Link to="/projects/new" className="atlas-primary-button">Create project</Link>}
          />
        ) : null}
      </AtlasCard>
    </div>
  );
}

function RegistryRow({ asset }: { asset: RegistryAsset }) {
  return (
    <tr className="align-top transition hover:bg-blue-50/40">
      <td className="px-4 py-4">
        <Link to={`/registry/${encodeURIComponent(asset.project_id)}`} className="font-semibold text-slate-950 hover:text-blue-700">{asset.name}</Link>
        <div className="mt-1 text-xs text-slate-500">{asset.project_id}</div>
        {asset.open_action_count > 0 && <div className="mt-2 text-xs font-semibold text-amber-700">{asset.open_action_count} open action{asset.open_action_count === 1 ? "" : "s"}</div>}
      </td>
      <td className="px-4 py-4 font-medium text-slate-700">{ASSET_TYPE_LABELS[asset.asset_type] ?? humanize(asset.asset_type)}</td>
      <td className="px-4 py-4"><div className="font-medium text-slate-900">{humanize(asset.workflow_type)}</div><div className="mt-1 text-xs text-slate-500">{TEMPLATE_LABELS[asset.template_id ?? ""] ?? humanize(asset.template_id, "General workflow")}</div></td>
      <td className="px-4 py-4"><div className="font-medium text-slate-900">{asset.owner_display_name}</div><div className="mt-1 text-xs text-slate-500">{humanize(asset.risk_tier)}</div></td>
      <td className="px-4 py-4"><RegistryStatus value={asset.lifecycle_status} /></td>
      <td className="px-4 py-4"><ReadinessCell status={asset.evidence_status} percent={asset.evidence_readiness_percent} /></td>
      <td className="px-4 py-4"><ReadinessCell status={asset.documentation_status} percent={asset.documentation_readiness_percent} /></td>
      <td className="px-4 py-4"><RegistryStatus value={asset.validation_status} />{asset.validation_score !== null && <div className="mt-2 text-xs font-semibold tabular-nums text-slate-600">Score {asset.validation_score}%</div>}</td>
      <td className="px-4 py-4"><RegistryStatus value={asset.recommendation_status} /></td>
      <td className="px-4 py-4"><RegistryStatus value={asset.implementation_status} /></td>
      <td className="px-4 py-4"><RegistryStatus value={asset.monitoring_status} /></td>
      <td className="px-4 py-4 font-semibold tabular-nums text-slate-800">{asset.monitoring_open_alert_count ?? 0}</td>
      <td className="px-4 py-4 text-xs leading-5 text-slate-600">{formatRegistryDate(asset.last_monitoring_run_at, true)}</td>
      <td className="px-4 py-4 text-xs leading-5 text-slate-600">{formatRegistryDate(asset.next_monitoring_due_at)}</td>
      <td className="px-4 py-4 text-xs leading-5 text-slate-600">{formatRegistryDate(asset.last_activity_at, true)}<div className="mt-1">{humanize(asset.latest_run_type, "No run recorded")}</div></td>
      <td className="px-4 py-4">
        <div className="flex justify-end gap-1">
          <Link to={`/registry/${encodeURIComponent(asset.project_id)}`} className="atlas-tertiary-button px-2" title="View registry detail"><ArrowRight size={16} /></Link>
          <Link to="/projects/open" className="atlas-tertiary-button px-2" title="Open project launcher"><FolderOpen size={16} /></Link>
          <Link to="/model-evidence-center" className="atlas-tertiary-button px-2" title="View Evidence Center"><ShieldCheck size={16} /></Link>
        </div>
      </td>
    </tr>
  );
}

function ReadinessCell({ status, percent }: { status: string; percent: number }) {
  return (
    <div>
      <div className="flex items-center justify-between gap-2"><RegistryStatus value={status} /><span className="text-xs font-semibold tabular-nums text-slate-600">{percent}%</span></div>
      <AtlasProgressBar value={percent} className="mt-2" />
    </div>
  );
}

function FilterSelect({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: Array<[string, string]> }) {
  return (
    <label>
      <span className="atlas-eyebrow">{label}</span>
      <select className="atlas-input mt-1" value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">All</option>
        {options.map(([optionValue, optionLabel]) => <option key={optionValue} value={optionValue}>{optionLabel}</option>)}
      </select>
    </label>
  );
}

function HeroFact({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="min-w-0 bg-slate-950/35 p-3">
      <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-sky-200">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold text-white" title={String(value)}>{value}</div>
    </div>
  );
}

function RegistryLoading() {
  return (
    <div className="grid gap-2" aria-label="Loading registry">
      {Array.from({ length: 6 }, (_, index) => <div key={index} className="h-16 animate-pulse rounded-lg bg-slate-100" />)}
    </div>
  );
}
