import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BriefcaseBusiness,
  CheckCircle2,
  ClipboardCheck,
  FileCheck2,
  FolderKanban,
  RefreshCw,
  ShieldCheck,
  UserRoundCheck,
} from "lucide-react";
import AtlasCard from "../components/ui/AtlasCard";
import AtlasEmptyState from "../components/ui/AtlasEmptyState";
import AtlasMetricCard from "../components/ui/AtlasMetricCard";
import AtlasPageHero from "../components/ui/AtlasPageHero";
import { ASSET_TYPE_LABELS, LIFECYCLE_ORDER, PortfolioBar, RegistryStatus, formatRegistryDate, humanize } from "../components/registry/RegistryPrimitives";
import {
  getRegistryActions,
  getRegistryActivity,
  getRegistryAssets,
  getRegistryOwners,
  getRegistrySummary,
  type RegistryAction,
  type RegistryActivity,
  type RegistryAsset,
  type RegistryOwner,
  type RegistrySummary,
} from "../lib/registryApi";
import { getValidationSummary, type ValidationSummary } from "../lib/validationApi";
import { getAdminSummary, type AdminSummary } from "../lib/adminSharing";
import { getMonitoringSummary, type MonitoringSummary } from "../lib/monitoringApi";

type DashboardData = {
  summary: RegistrySummary;
  assets: RegistryAsset[];
  actions: RegistryAction[];
  activity: RegistryActivity[];
  owners: RegistryOwner[];
  validation: ValidationSummary;
  monitoring: MonitoringSummary;
  access: AdminSummary | null;
};

export default function ManagementDashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [summary, assets, actions, activity, owners, validation, monitoring, accessPayload] = await Promise.all([
        getRegistrySummary(),
        getRegistryAssets({ limit: 500 }),
        getRegistryActions({ limit: 100 }),
        getRegistryActivity({ limit: 50 }),
        getRegistryOwners(),
        getValidationSummary(),
        getMonitoringSummary(),
        getAdminSummary().catch(() => null),
      ]);
      setData({ summary, assets: assets.assets, actions: actions.actions, activity: activity.activity, owners: owners.owners, validation, monitoring, access: accessPayload?.summary ?? null });
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "ATLAS could not load the management portfolio.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="atlas-page-shell atlas-theme-analytics" data-testid="management-dashboard">
      <AtlasPageHero
        dark
        eyebrow="Enterprise portfolio command center"
        title="ATLAS Management Dashboard"
        subtitle="Portfolio view of governed models, optimization studies, experiments, evidence readiness, validation status, and implementation activity."
        actions={(
          <>
            <Link to="/registry" className="atlas-primary-button bg-white text-slate-950 hover:bg-slate-100">
              <FolderKanban size={16} /> Open Registry
            </Link>
            <button type="button" className="atlas-secondary-button border-white/30 bg-white/10 text-white hover:bg-white/20" onClick={() => void load()} disabled={loading}>
              <RefreshCw size={16} className={loading ? "animate-spin" : ""} /> Refresh portfolio
            </button>
          </>
        )}
        aside={(
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-white/20 bg-white/15">
            <HeroFact label="Data source" value="ATLAS SQLite" />
            <HeroFact label="Portfolio state" value={loading ? "Refreshing" : error ? "Unavailable" : "Synchronized"} />
            <HeroFact label="Last rollup" value={data ? formatRegistryDate(data.summary.generated_at, true) : "Pending"} />
            <HeroFact label="Stale assets" value={data?.summary.stale_assets_count ?? 0} />
          </div>
        )}
      />

      {error && (
        <AtlasCard tone="attention" title="Management portfolio unavailable">
          <p className="text-sm leading-6">{error}</p>
          <button type="button" className="atlas-secondary-button mt-4" onClick={() => void load()}>Try again</button>
        </AtlasCard>
      )}

      {loading && !data ? <DashboardLoading /> : data ? <DashboardContent data={data} /> : !error ? (
        <AtlasEmptyState title="No portfolio data is available" body="ATLAS could not find persisted registry records." />
      ) : null}
    </div>
  );
}

function DashboardContent({ data }: { data: DashboardData }) {
  const { summary } = data;
  return (
    <>
      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-8" aria-label="Portfolio metrics">
        <AtlasMetricCard label="Total assets" value={summary.total_assets} detail="Persisted analytical assets" icon={<BriefcaseBusiness size={18} />} />
        <AtlasMetricCard label="Active development" value={summary.assets_by_status.Development ?? 0} detail="Workflows in progress" icon={<Activity size={18} />} tone="info" />
        <AtlasMetricCard label="Ready for review" value={summary.ready_for_review} detail="Awaiting governance review" icon={<ClipboardCheck size={18} />} tone={summary.ready_for_review ? "warning" : "neutral"} />
        <AtlasMetricCard label="Validation complete" value={summary.validation_complete_count} detail={`${summary.validation_pending_count} pending`} icon={<CheckCircle2 size={18} />} tone="success" />
        <AtlasMetricCard label="Evidence ready" value={summary.evidence_ready_count} detail={`${summary.evidence_incomplete_count} incomplete`} icon={<ShieldCheck size={18} />} tone="success" />
        <AtlasMetricCard label="Documentation ready" value={summary.documentation_ready_count} detail={`${summary.documentation_incomplete_count} incomplete`} icon={<FileCheck2 size={18} />} tone="success" />
        <AtlasMetricCard label="Open actions" value={summary.open_action_count} detail="Derived governance gaps" icon={<AlertTriangle size={18} />} tone={summary.open_action_count ? "warning" : "success"} />
        <AtlasMetricCard label="Recent activity" value={summary.recent_activity_count} detail="Past 30 days" icon={<Activity size={18} />} tone="info" />
      </section>

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5" aria-label="Validation metrics">
        <AtlasMetricCard label="Validation queue" value={data.validation.total_cases} detail="Independent cases" icon={<ClipboardCheck size={18} />} tone="info" />
        <AtlasMetricCard label="In review" value={data.validation.in_review} detail={`${data.validation.submitted} submitted`} icon={<ShieldCheck size={18} />} tone={data.validation.in_review ? "info" : "neutral"} />
        <AtlasMetricCard label="Returned" value={data.validation.returned} detail="Owner action required" icon={<AlertTriangle size={18} />} tone={data.validation.returned ? "warning" : "success"} />
        <AtlasMetricCard label="Validation findings" value={data.validation.open_findings} detail="Open independent findings" icon={<AlertTriangle size={18} />} tone={data.validation.open_findings ? "warning" : "success"} />
        <AtlasMetricCard label="Approved cases" value={data.validation.approved} detail="Approved or conditional" icon={<CheckCircle2 size={18} />} tone="success" />
      </section>

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5" aria-label="Production monitoring metrics">
        <AtlasMetricCard label="Assets under monitoring" value={data.monitoring.active_plans} detail={`${data.monitoring.total_plans} plans defined`} icon={<Activity size={18} />} tone={data.monitoring.active_plans ? "success" : "neutral"} />
        <AtlasMetricCard label="Missing monitoring plans" value={Math.max(0, summary.implementation_planned + summary.monitoring - data.monitoring.total_plans)} detail="Implemented or planned assets without plans" icon={<AlertTriangle size={18} />} tone={summary.implementation_planned + summary.monitoring > data.monitoring.total_plans ? "warning" : "success"} />
        <AtlasMetricCard label="Open monitoring alerts" value={data.monitoring.open_alerts} detail={`${data.monitoring.high_critical_alerts} high or critical`} icon={<AlertTriangle size={18} />} tone={data.monitoring.open_alerts ? "warning" : "success"} />
        <AtlasMetricCard label="Monitoring runs" value={data.monitoring.runs_this_period} detail="Recent production control runs" icon={<RefreshCw size={18} />} tone="info" />
        <AtlasMetricCard label="Revalidation triggers" value={data.monitoring.actions_open} detail="Open monitoring actions" icon={<ShieldCheck size={18} />} tone={data.monitoring.actions_open ? "warning" : "success"} />
      </section>

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5" aria-label="Access and sharing metrics">
        <AtlasMetricCard label="Active users" value={data.access?.activeUsers ?? "Restricted"} detail="Admin-visible access rollup" icon={<UserRoundCheck size={18} />} tone={data.access ? "info" : "neutral"} />
        <AtlasMetricCard label="Shared resources" value={data.access?.activeSharedResources ?? "Restricted"} detail="Active explicit permissions" icon={<ShieldCheck size={18} />} tone={data.access?.activeSharedResources ? "info" : "neutral"} />
        <AtlasMetricCard label="Pending access" value={data.access?.pendingAccessRequests ?? "Restricted"} detail="Access requests awaiting review" icon={<AlertTriangle size={18} />} tone={data.access?.pendingAccessRequests ? "warning" : "success"} />
        <AtlasMetricCard label="User groups" value={data.access?.groupCount ?? "Restricted"} detail="Governed collaboration groups" icon={<UserRoundCheck size={18} />} tone="info" />
        <AtlasMetricCard label="Shareable types" value={data.access?.resourceTypes.length ?? "Restricted"} detail="Resource permission model" icon={<FileCheck2 size={18} />} tone="info" />
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(320px,0.85fr)]">
        <AtlasCard eyebrow="Portfolio health" title="Lifecycle distribution" action={<Link to="/registry" className="atlas-tertiary-button">Review assets <ArrowRight size={15} /></Link>}>
          {summary.total_assets ? LIFECYCLE_ORDER.map((status, index) => (
            <PortfolioBar
              key={status}
              label={status}
              value={summary.assets_by_status[status] ?? 0}
              total={summary.total_assets}
              color={index > 5 ? "bg-emerald-600" : index > 3 ? "bg-teal-600" : index > 1 ? "bg-blue-600" : "bg-slate-500"}
            />
          )) : <AtlasEmptyState title="No governed assets yet" body="Create or restore a project to populate lifecycle health." />}
        </AtlasCard>

        <AtlasCard eyebrow="Portfolio composition" title="Analytical asset mix">
          {Object.keys(summary.assets_by_type).length ? Object.entries(summary.assets_by_type)
            .sort(([, left], [, right]) => right - left)
            .map(([assetType, count]) => (
              <PortfolioBar key={assetType} label={ASSET_TYPE_LABELS[assetType] ?? humanize(assetType)} value={count} total={summary.total_assets} color="bg-cyan-700" />
            )) : <AtlasEmptyState title="No asset mix available" body="Asset types are derived from persisted project records." />}
        </AtlasCard>
      </section>

      <AtlasCard eyebrow="Governance queue" title="Open governance actions" action={<span className="text-xs font-semibold text-slate-500">Real gaps only</span>}>
        {data.actions.length ? (
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="min-w-[920px] w-full border-collapse text-left text-sm">
              <thead className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
                <tr><th className="px-4 py-3">Asset</th><th className="px-4 py-3">Issue</th><th className="px-4 py-3">Severity</th><th className="px-4 py-3">Owner</th><th className="px-4 py-3">Recommended action</th><th className="px-4 py-3 text-right">Open</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {data.actions.slice(0, 12).map((action) => (
                  <tr key={action.action_id} className="align-top hover:bg-blue-50/40">
                    <td className="px-4 py-3 font-semibold text-slate-950">{action.project_name}</td>
                    <td className="px-4 py-3"><div className="font-medium text-slate-900">{action.title}</div><div className="mt-1 text-xs leading-5 text-slate-500">{action.description}</div></td>
                    <td className="px-4 py-3"><RegistryStatus value={action.severity} /></td>
                    <td className="px-4 py-3 text-slate-700">{action.owner}</td>
                    <td className="max-w-sm px-4 py-3 text-xs leading-5 text-slate-600">{action.recommended_next_step}</td>
                    <td className="px-4 py-3 text-right"><Link to={`/registry/${encodeURIComponent(action.project_id)}`} className="atlas-tertiary-button">View <ArrowRight size={14} /></Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <AtlasEmptyState
            title="No open governance actions"
            body="Persisted assets currently have no missing evidence, documentation, validation, implementation, monitoring, export, stale-project, or failed-run actions."
            action={<Link to="/registry" className="atlas-secondary-button">Inspect the registry</Link>}
          />
        )}
      </AtlasCard>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(360px,0.8fr)]">
        <AtlasCard eyebrow="Accountability" title="Portfolio owners" action={<Link to="/admin/users" className="atlas-tertiary-button"><UserRoundCheck size={15} /> User administration</Link>}>
          {data.owners.length ? (
            <div className="overflow-x-auto">
              <table className="min-w-[720px] w-full border-collapse text-left text-sm">
                <thead className="border-b border-slate-200 text-[11px] uppercase tracking-wide text-slate-500">
                  <tr><th className="pb-3 pr-4">Owner</th><th className="pb-3 px-3">Role</th><th className="pb-3 px-3 text-right">Active assets</th><th className="pb-3 px-3 text-right">Ready for review</th><th className="pb-3 px-3 text-right">Open actions</th><th className="pb-3 pl-3">Last activity</th></tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {data.owners.map((owner) => (
                    <tr key={owner.user_id} className="hover:bg-slate-50">
                      <td className="py-3 pr-4"><div className="font-semibold text-slate-950">{owner.display_name}</div><div className="text-xs text-slate-500">{owner.user_id}</div></td>
                      <td className="px-3 py-3 text-slate-700">{humanize(owner.role)}</td>
                      <td className="px-3 py-3 text-right font-semibold tabular-nums">{owner.active_assets}</td>
                      <td className="px-3 py-3 text-right tabular-nums">{owner.ready_for_review}</td>
                      <td className="px-3 py-3 text-right tabular-nums">{owner.open_actions}</td>
                      <td className="py-3 pl-3 text-xs text-slate-600">{formatRegistryDate(owner.last_active_at, true)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <AtlasEmptyState title="No owner records available" body="Owner accountability appears after persisted users own analytical assets." />}
        </AtlasCard>

        <AtlasCard eyebrow="Audit rollup" title="Recent portfolio activity" action={<Link to="/audit" className="atlas-tertiary-button">Full audit log <ArrowRight size={15} /></Link>}>
          {data.activity.length ? (
            <ol className="divide-y divide-slate-100">
              {data.activity.slice(0, 10).map((event, index) => (
                <li key={`${event.event_type}-${event.source_id}-${index}`} className="grid grid-cols-[12px_minmax(0,1fr)] gap-3 py-3 first:pt-0 last:pb-0">
                  <span className="mt-1.5 h-2.5 w-2.5 rounded-full bg-blue-600 ring-4 ring-blue-50" />
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="font-semibold text-slate-950">{event.title}</div>
                      <div className="text-[11px] font-medium text-slate-500">{formatRegistryDate(event.occurred_at, true)}</div>
                    </div>
                    <div className="mt-1 text-xs leading-5 text-slate-600">{event.project_name ? `${event.project_name} | ` : ""}{event.summary || humanize(event.event_type)}</div>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                      <span>{event.user_display_name}</span>
                      {event.status && <RegistryStatus value={event.status} />}
                      {event.project_id && <Link to={`/registry/${encodeURIComponent(event.project_id)}`} className="font-semibold text-blue-700 hover:text-blue-900">Registry detail</Link>}
                    </div>
                  </div>
                </li>
              ))}
            </ol>
          ) : <AtlasEmptyState title="No persisted activity yet" body="Audit, evidence, run, decision, documentation, and export events will appear here." />}
        </AtlasCard>
      </section>
    </>
  );
}

function HeroFact({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="min-h-[58px] min-w-0 bg-slate-950/35 p-3">
      <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-sky-200">{label}</div>
      <div className="mt-1 break-words text-xs font-semibold leading-4 text-white" title={String(value)}>{value}</div>
    </div>
  );
}

function DashboardLoading() {
  return (
    <div className="grid gap-4" aria-label="Loading management dashboard">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 8 }, (_, index) => <div key={index} className="h-28 animate-pulse rounded-lg border border-slate-200 bg-white" />)}
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <div className="h-80 animate-pulse rounded-lg border border-slate-200 bg-white" />
        <div className="h-80 animate-pulse rounded-lg border border-slate-200 bg-white" />
      </div>
    </div>
  );
}
