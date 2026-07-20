import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Activity, AlertTriangle, ArrowRight, Bell, CheckCircle2, FilterX, Gauge, PlayCircle, RefreshCw, Search, ShieldCheck } from "lucide-react";
import AtlasCard from "../components/ui/AtlasCard";
import AtlasEmptyState from "../components/ui/AtlasEmptyState";
import AtlasMetricCard from "../components/ui/AtlasMetricCard";
import AtlasPageHero from "../components/ui/AtlasPageHero";
import AtlasStatusBadge from "../components/ui/AtlasStatusBadge";
import {
  getMonitoringSummary,
  listMonitoringPlans,
  monitoringAlertStatusLabels,
  monitoringPlanStatusLabels,
  monitoringSeverityLabels,
  monitoringStatusTone,
  type MonitoringAlert,
  type MonitoringPlan,
  type MonitoringSummary,
} from "../lib/monitoringApi";

type Filters = {
  search: string;
  workflow_type: string;
  owner_user_id: string;
  status: string;
  severity: string;
  dueSoon: boolean;
};

const emptyFilters: Filters = { search: "", workflow_type: "", owner_user_id: "", status: "", severity: "", dueSoon: false };

export default function MonitoringCenter() {
  const [summary, setSummary] = useState<MonitoringSummary | null>(null);
  const [plans, setPlans] = useState<MonitoringPlan[]>([]);
  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [nextSummary, planPayload] = await Promise.all([
        getMonitoringSummary(),
        listMonitoringPlans({ search: filters.search, workflow_type: filters.workflow_type, owner_user_id: filters.owner_user_id, status: filters.status, limit: 500 }),
      ]);
      setSummary(nextSummary);
      setPlans(planPayload.items);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "ATLAS could not load monitoring data.");
    } finally {
      setLoading(false);
    }
  }, [filters.owner_user_id, filters.search, filters.status, filters.workflow_type]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), filters.search ? 250 : 0);
    return () => window.clearTimeout(timer);
  }, [load, filters.search]);

  const filteredAlerts = useMemo(() => {
    const alerts = summary?.latest_alerts ?? [];
    return alerts.filter((alert) => !filters.severity || alert.severity === filters.severity);
  }, [summary, filters.severity]);
  const activeFilterCount = Object.values(filters).filter(Boolean).length;
  const workflowOptions = useMemo(() => [...new Set(plans.map((plan) => plan.workflow_type).filter(Boolean) as string[])].sort(), [plans]);
  const ownerOptions = useMemo(() => [...new Map(plans.filter((plan) => plan.monitoring_owner_user_id).map((plan) => [plan.monitoring_owner_user_id as string, plan.monitoring_owner_name || plan.monitoring_owner_user_id as string])).entries()], [plans]);

  return (
    <div className="atlas-page-shell atlas-theme-analytics" data-testid="monitoring-center">
      <AtlasPageHero
        dark
        eyebrow="Production control layer"
        title="ATLAS Monitoring Center"
        subtitle="Track production performance, data drift, decision stability, alerts, owner actions, and revalidation triggers across governed analytical assets."
        actions={(
          <>
            <button type="button" className="atlas-secondary-button border-white/30 bg-white/10 text-white hover:bg-white/20" onClick={() => void load()} disabled={loading}>
              <RefreshCw size={16} className={loading ? "animate-spin" : ""} /> Refresh monitoring
            </button>
            <Link to="/registry" className="atlas-primary-button bg-white text-slate-950 hover:bg-slate-100">Open Registry</Link>
          </>
        )}
        aside={(
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-white/20 bg-white/15">
            <HeroFact label="Source" value="SQLite monitoring" />
            <HeroFact label="Plans" value={summary?.total_plans ?? 0} />
            <HeroFact label="Open alerts" value={summary?.open_alerts ?? 0} />
            <HeroFact label="State" value={loading ? "Refreshing" : error ? "Unavailable" : "Current"} />
          </div>
        )}
      />

      {error && (
        <AtlasCard tone="attention" title="Monitoring data unavailable">
          <p className="text-sm leading-6">{error}</p>
          <button type="button" className="atlas-secondary-button mt-4" onClick={() => void load()}>Try again</button>
        </AtlasCard>
      )}

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-8" aria-label="Monitoring summary cards">
        <AtlasMetricCard label="Active plans" value={summary?.active_plans ?? 0} detail="Production monitoring plans" icon={<ShieldCheck size={18} />} tone="success" />
        <AtlasMetricCard label="Missing plans" value="Review" detail="Registry integration flags assets without plans" icon={<Gauge size={18} />} tone="warning" />
        <AtlasMetricCard label="Runs this period" value={summary?.runs_this_period ?? 0} detail="Persisted monitoring runs" icon={<PlayCircle size={18} />} tone="info" />
        <AtlasMetricCard label="Open alerts" value={summary?.open_alerts ?? 0} detail="Unresolved monitoring alerts" icon={<Bell size={18} />} tone={summary?.open_alerts ? "warning" : "success"} />
        <AtlasMetricCard label="High/Critical" value={summary?.high_critical_alerts ?? 0} detail="Owner attention required" icon={<AlertTriangle size={18} />} tone={summary?.high_critical_alerts ? "danger" : "success"} />
        <AtlasMetricCard label="Breaches" value={summary?.breaches ?? 0} detail="Run-level breach count" icon={<AlertTriangle size={18} />} tone={summary?.breaches ? "danger" : "success"} />
        <AtlasMetricCard label="Warnings" value={summary?.warnings ?? 0} detail="Run-level warning count" icon={<Activity size={18} />} tone={summary?.warnings ? "warning" : "success"} />
        <AtlasMetricCard label="Next reviews" value={summary?.next_reviews_due ?? 0} detail="Plans with scheduled review dates" icon={<CheckCircle2 size={18} />} tone="info" />
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(360px,0.9fr)]">
        <AtlasCard eyebrow="Monitoring portfolio health" title="Status, severity, and breach mix">
          {summary ? (
            <div className="grid gap-4 lg:grid-cols-3">
              <DistributionBlock title="Plans by status" values={summary.plans_by_status} labels={monitoringPlanStatusLabels} />
              <DistributionBlock title="Alerts by severity" values={summary.alerts_by_severity} labels={monitoringSeverityLabels} />
              <DistributionBlock title="Breaches by workflow" values={summary.breaches_by_workflow_type} />
            </div>
          ) : <SkeletonRows />}
        </AtlasCard>

        <AtlasCard eyebrow="Monitoring activity" title="Latest production events">
          {summary?.recent_events?.length ? (
            <div className="space-y-2">
              {summary.recent_events.slice(0, 8).map((event) => (
                <div key={event.event_id} className="rounded-lg border border-slate-200 bg-white p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold text-slate-950">{event.title}</div>
                      <div className="mt-1 text-xs leading-5 text-slate-500">{event.summary || event.event_type}</div>
                    </div>
                    <div className="text-right text-[11px] font-semibold text-slate-400">{formatDate(event.created_at)}</div>
                  </div>
                </div>
              ))}
            </div>
          ) : <AtlasEmptyState title="No monitoring activity yet" body="Monitoring events will appear after plans, runs, alerts, and remediation actions are created." />}
        </AtlasCard>
      </section>

      <AtlasCard eyebrow="Monitoring controls" title="Filter production plans" action={activeFilterCount ? <button type="button" className="atlas-tertiary-button" onClick={() => setFilters(emptyFilters)}><FilterX size={15} /> Clear filters</button> : undefined}>
        <div className="grid gap-3 lg:grid-cols-6">
          <label className="relative lg:col-span-2">
            <span className="atlas-eyebrow">Search</span>
            <Search size={16} className="pointer-events-none absolute bottom-2.5 left-3 text-slate-400" />
            <input className="atlas-input mt-1 pl-9" value={filters.search} onChange={(event) => setFilters((current) => ({ ...current, search: event.target.value }))} placeholder="Asset, plan, owner..." />
          </label>
          <FilterSelect label="Workflow" value={filters.workflow_type} onChange={(value) => setFilters((current) => ({ ...current, workflow_type: value }))} options={workflowOptions.map((value) => [value, humanize(value)])} />
          <FilterSelect label="Owner" value={filters.owner_user_id} onChange={(value) => setFilters((current) => ({ ...current, owner_user_id: value }))} options={ownerOptions as Array<[string, string]>} />
          <FilterSelect label="Plan status" value={filters.status} onChange={(value) => setFilters((current) => ({ ...current, status: value }))} options={Object.entries(monitoringPlanStatusLabels)} />
          <FilterSelect label="Alert severity" value={filters.severity} onChange={(value) => setFilters((current) => ({ ...current, severity: value }))} options={Object.entries(monitoringSeverityLabels)} />
        </div>
      </AtlasCard>

      <AtlasCard eyebrow="Monitoring plan table" title={`${plans.length} monitoring plan${plans.length === 1 ? "" : "s"}`}>
        {loading && !plans.length ? <SkeletonRows /> : plans.length ? (
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="min-w-[1260px] w-full text-left text-sm">
              <thead className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
                <tr><th className="px-4 py-3">Asset</th><th className="px-4 py-3">Workflow</th><th className="px-4 py-3">Owner</th><th className="px-4 py-3">Plan status</th><th className="px-4 py-3">Cadence</th><th className="px-4 py-3">Last run</th><th className="px-4 py-3">Next run</th><th className="px-4 py-3">Overall</th><th className="px-4 py-3">Open alerts</th><th className="px-4 py-3 text-right">Actions</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {plans.map((plan) => <PlanRow key={plan.monitoring_plan_id} plan={plan} />)}
              </tbody>
            </table>
          </div>
        ) : (
          <AtlasEmptyState title="No monitoring plans exist yet" body="Create a monitoring plan from Project Overview, Registry Asset Detail, or a project monitoring route." action={<Link to="/registry" className="atlas-primary-button">Choose an asset</Link>} />
        )}
      </AtlasCard>

      <AtlasCard eyebrow="Alerts queue" title="Open monitoring alerts">
        {filteredAlerts.length ? (
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="min-w-[1160px] w-full text-left text-sm">
              <thead className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
                <tr><th className="px-4 py-3">Severity</th><th className="px-4 py-3">Title</th><th className="px-4 py-3">Asset</th><th className="px-4 py-3">Metric</th><th className="px-4 py-3">Observed</th><th className="px-4 py-3">Threshold</th><th className="px-4 py-3">Owner</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">Created</th><th className="px-4 py-3 text-right">Action</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {filteredAlerts.map((alert) => <AlertRow key={alert.alert_id} alert={alert} />)}
              </tbody>
            </table>
          </div>
        ) : <AtlasEmptyState title="No open alerts match this view" body="Breaches and warnings from monitoring runs will populate this queue." />}
      </AtlasCard>
    </div>
  );
}

function PlanRow({ plan }: { plan: MonitoringPlan }) {
  return (
    <tr className="align-top hover:bg-blue-50/40">
      <td className="px-4 py-3"><div className="font-semibold text-slate-950">{plan.project_name || plan.plan_name}</div><div className="text-xs text-slate-500">{plan.project_id}</div></td>
      <td className="px-4 py-3 text-slate-700">{humanize(plan.workflow_type || "generic")}</td>
      <td className="px-4 py-3 text-slate-700">{plan.monitoring_owner_name || plan.monitoring_owner_user_id || "Unassigned"}</td>
      <td className="px-4 py-3"><AtlasStatusBadge tone={monitoringStatusTone(plan.plan_status) as any}>{monitoringPlanStatusLabels[plan.plan_status] || humanize(plan.plan_status)}</AtlasStatusBadge></td>
      <td className="px-4 py-3 text-slate-700">{plan.monitoring_cadence || "Not set"}</td>
      <td className="px-4 py-3 text-xs text-slate-600">{formatDate(plan.last_run_at)}</td>
      <td className="px-4 py-3 text-xs text-slate-600">{formatDate(plan.next_monitoring_date)}</td>
      <td className="px-4 py-3"><AtlasStatusBadge tone={monitoringStatusTone(plan.overall_status) as any}>{humanize(plan.overall_status || "current")}</AtlasStatusBadge></td>
      <td className="px-4 py-3 font-semibold tabular-nums text-slate-950">{plan.open_alert_count ?? 0}</td>
      <td className="px-4 py-3 text-right"><Link to={`/monitoring/${encodeURIComponent(plan.monitoring_plan_id)}`} className="atlas-tertiary-button">Open <ArrowRight size={14} /></Link></td>
    </tr>
  );
}

function AlertRow({ alert }: { alert: MonitoringAlert }) {
  return (
    <tr className="align-top hover:bg-amber-50/40">
      <td className="px-4 py-3"><AtlasStatusBadge tone={monitoringStatusTone(alert.severity) as any}>{monitoringSeverityLabels[alert.severity] || humanize(alert.severity)}</AtlasStatusBadge></td>
      <td className="px-4 py-3"><div className="font-semibold text-slate-950">{alert.title}</div><div className="text-xs text-slate-500">{alert.description}</div></td>
      <td className="px-4 py-3 text-xs text-slate-600">{alert.project_id}</td>
      <td className="px-4 py-3 text-slate-700">{alert.metric_name || "General"}</td>
      <td className="px-4 py-3 tabular-nums">{formatNumber(alert.observed_value)}</td>
      <td className="px-4 py-3 tabular-nums">{formatNumber(alert.threshold_value)}</td>
      <td className="px-4 py-3 text-slate-700">{alert.owner_name || alert.owner_user_id || "Unassigned"}</td>
      <td className="px-4 py-3"><AtlasStatusBadge tone={monitoringStatusTone(alert.status) as any}>{monitoringAlertStatusLabels[alert.status] || humanize(alert.status)}</AtlasStatusBadge></td>
      <td className="px-4 py-3 text-xs text-slate-600">{formatDate(alert.created_at)}</td>
      <td className="px-4 py-3 text-right">{alert.monitoring_plan_id && <Link className="atlas-tertiary-button" to={`/monitoring/${encodeURIComponent(alert.monitoring_plan_id)}`}>Review</Link>}</td>
    </tr>
  );
}

function DistributionBlock({ title, values, labels = {} }: { title: string; values: Record<string, number>; labels?: Record<string, string> }) {
  const total = Math.max(1, Object.values(values).reduce((sum, value) => sum + value, 0));
  const entries = Object.entries(values);
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
      <div className="text-sm font-semibold text-slate-950">{title}</div>
      <div className="mt-3 space-y-3">
        {entries.length ? entries.map(([key, value]) => (
          <div key={key}>
            <div className="mb-1 flex justify-between text-xs font-semibold text-slate-600"><span>{labels[key] || humanize(key)}</span><span>{value}</span></div>
            <div className="h-2 rounded-full bg-slate-200"><div className="h-2 rounded-full bg-blue-600" style={{ width: `${Math.round((value / total) * 100)}%` }} /></div>
          </div>
        )) : <div className="text-sm text-slate-500">No records yet.</div>}
      </div>
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

function SkeletonRows() {
  return <div className="grid gap-2">{Array.from({ length: 5 }, (_, index) => <div key={index} className="h-14 animate-pulse rounded-lg bg-slate-100" />)}</div>;
}

function humanize(value?: string, fallback = "Not available") {
  const text = String(value || "").trim();
  return text ? text.replace(/[_-]/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase()) : fallback;
}

function formatDate(value?: string) {
  if (!value) return "Not scheduled";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString();
}

function formatNumber(value?: number) {
  return typeof value === "number" ? value.toLocaleString(undefined, { maximumFractionDigits: 4 }) : "Not set";
}
