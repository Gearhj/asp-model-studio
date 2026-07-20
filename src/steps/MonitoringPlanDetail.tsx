import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Activity, AlertTriangle, ArrowRight, Download, FileText, PlayCircle, RefreshCw, Share2, ShieldCheck } from "lucide-react";
import AtlasCard from "../components/ui/AtlasCard";
import AtlasEmptyState from "../components/ui/AtlasEmptyState";
import AtlasMetricCard from "../components/ui/AtlasMetricCard";
import AtlasPageHero from "../components/ui/AtlasPageHero";
import AtlasStatusBadge from "../components/ui/AtlasStatusBadge";
import ShareResourceDialog from "../components/sharing/ShareResourceDialog";
import {
  acceptMonitoringRisk,
  activateMonitoringPlan,
  acknowledgeMonitoringAlert,
  createMonitoringRun,
  createRevalidationReview,
  getMonitoringPlan,
  getProjectMonitoringPlan,
  monitoringAlertStatusLabels,
  monitoringObservationStatusLabels,
  monitoringPlanStatusLabels,
  monitoringRunStatusLabels,
  monitoringSeverityLabels,
  monitoringStatusTone,
  pauseMonitoringPlan,
  resolveMonitoringAlert,
  retireMonitoringPlan,
  seedMonitoringMetrics,
  startMonitoringRun,
  type MonitoringAlert,
  type MonitoringMetric,
  type MonitoringObservation,
  type MonitoringPlanDetail as MonitoringPlanDetailPayload,
} from "../lib/monitoringApi";

export default function MonitoringPlanDetail() {
  const params = useParams();
  const planId = params.monitoringPlanId;
  const projectId = params.projectId;
  const [detail, setDetail] = useState<MonitoringPlanDetailPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [shareOpen, setShareOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const payload = planId ? await getMonitoringPlan(planId) : await getProjectMonitoringPlan(projectId || "");
      setDetail(payload);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "ATLAS could not load the monitoring plan.");
      setDetail(null);
    } finally {
      setLoading(false);
    }
  }, [planId, projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function execute(label: string, action: () => Promise<unknown>) {
    setBusy(label);
    setError("");
    try {
      await action();
      await load();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : `ATLAS could not complete ${label}.`);
    } finally {
      setBusy("");
    }
  }

  async function runMonitoring() {
    if (!detail) return;
    await execute("run monitoring", async () => {
      const created = await createMonitoringRun(detail.plan.monitoring_plan_id, { run_name: `${detail.plan.plan_name} run`, summary: "Manual monitoring run from ATLAS Monitoring Center." });
      await startMonitoringRun(created.run.monitoring_run_id);
    });
  }

  const latestRun = detail?.runs?.[0];
  const openAlerts = detail?.alerts.filter((alert) => !["resolved", "accepted_risk", "closed"].includes(alert.status)) ?? [];
  const trendRows = useMemo(() => buildTrend(detail?.observations ?? []), [detail?.observations]);

  if (loading && !detail) {
    return <div className="atlas-page-shell"><AtlasCard title="Loading Monitoring Plan"><div className="h-48 animate-pulse rounded-xl bg-slate-100" /></AtlasCard></div>;
  }

  if (!detail) {
    return (
      <div className="atlas-page-shell">
        <AtlasEmptyState title="Monitoring plan not available" body={error || "Create a monitoring plan from Project Overview or the Registry Asset Detail page."} action={<Link to="/monitoring" className="atlas-primary-button">Open Monitoring Center</Link>} />
      </div>
    );
  }

  const { plan } = detail;

  return (
    <div className="atlas-page-shell atlas-theme-analytics" data-testid="monitoring-plan-detail">
      <AtlasPageHero
        dark
        eyebrow="Production monitoring plan"
        title="Monitoring Plan"
        subtitle="Govern production metrics, thresholds, observations, alerts, remediation, evidence, documentation, and revalidation triggers."
        actions={(
          <>
            <button type="button" className="atlas-secondary-button border-white/30 bg-white/10 text-white hover:bg-white/20" onClick={() => void load()} disabled={loading}><RefreshCw size={16} className={loading ? "animate-spin" : ""} /> Refresh</button>
            <button type="button" className="atlas-primary-button bg-white text-slate-950 hover:bg-slate-100" onClick={runMonitoring} disabled={Boolean(busy) || !detail.metrics.length}><PlayCircle size={16} /> Run Monitoring</button>
          </>
        )}
        aside={(
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-white/20 bg-white/15">
            <HeroFact label="Asset" value={plan.project_name || plan.project_id} />
            <HeroFact label="Workflow" value={humanize(plan.workflow_type)} />
            <HeroFact label="Owner" value={plan.monitoring_owner_name || "Unassigned"} />
            <HeroFact label="Status" value={monitoringPlanStatusLabels[plan.plan_status] || humanize(plan.plan_status)} />
          </div>
        )}
      />

      {error && (
        <AtlasCard tone="attention" title="Monitoring action failed">
          <p className="text-sm leading-6">{error}</p>
        </AtlasCard>
      )}

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-8">
        <AtlasMetricCard label="Plan status" value={monitoringPlanStatusLabels[plan.plan_status] || humanize(plan.plan_status)} detail={plan.monitoring_cadence || "Cadence not set"} icon={<ShieldCheck size={18} />} tone={monitoringStatusTone(plan.plan_status) as any} />
        <AtlasMetricCard label="Owner" value={plan.monitoring_owner_name || "Unassigned"} detail="Monitoring accountable owner" icon={<Activity size={18} />} />
        <AtlasMetricCard label="Last run" value={formatDate(plan.last_run_at)} detail={latestRun ? monitoringRunStatusLabels[latestRun.run_status] : "No run"} icon={<PlayCircle size={18} />} />
        <AtlasMetricCard label="Next run" value={formatDate(plan.next_monitoring_date)} detail="Scheduled monitoring date" icon={<RefreshCw size={18} />} />
        <AtlasMetricCard label="Overall" value={humanize(plan.overall_status || "Current")} detail="Latest run status" icon={<GaugeIcon />} tone={monitoringStatusTone(plan.overall_status) as any} />
        <AtlasMetricCard label="Open alerts" value={openAlerts.length} detail={`${detail.alerts.length} total alerts`} icon={<AlertTriangle size={18} />} tone={openAlerts.length ? "warning" : "success"} />
        <AtlasMetricCard label="Metrics" value={detail.metrics.length} detail="Threshold rules" icon={<Activity size={18} />} />
        <AtlasMetricCard label="Evidence" value={latestRun?.evidence_ref ? "Captured" : "Pending"} detail="Monitoring run artifact" icon={<FileText size={18} />} tone={latestRun?.evidence_ref ? "success" : "neutral"} />
      </section>

      <AtlasCard
        eyebrow="Plan actions"
        title={plan.plan_name}
        action={<button type="button" className="atlas-secondary-button" onClick={() => setShareOpen(true)}><Share2 size={15} /> Share monitoring plan</button>}
      >
        <div className="flex flex-wrap gap-2">
          <button type="button" className="atlas-primary-button" disabled={Boolean(busy)} onClick={() => void execute("activate plan", () => activateMonitoringPlan(plan.monitoring_plan_id))}>Activate plan</button>
          <button type="button" className="atlas-secondary-button" disabled={Boolean(busy)} onClick={() => void execute("pause plan", () => pauseMonitoringPlan(plan.monitoring_plan_id))}>Pause plan</button>
          <button type="button" className="atlas-secondary-button" disabled={Boolean(busy)} onClick={() => void execute("retire plan", () => retireMonitoringPlan(plan.monitoring_plan_id))}>Retire plan</button>
          <button type="button" className="atlas-secondary-button" disabled={Boolean(busy)} onClick={() => void execute("seed metrics", () => seedMonitoringMetrics(plan.monitoring_plan_id))}>Seed from workflow template</button>
          <button type="button" className="atlas-secondary-button" onClick={() => exportJson("monitoring-report.json", detail)}><Download size={15} /> Export monitoring package</button>
          <button type="button" className="atlas-secondary-button" onClick={() => exportCsv("monitoring-observations.csv", detail.observations)}><Download size={15} /> Export observations CSV</button>
          <button type="button" className="atlas-secondary-button" onClick={() => exportCsv("monitoring-alerts.csv", detail.alerts)}><Download size={15} /> Export alerts CSV</button>
        </div>
        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          <InfoBlock label="Monitoring scope" value={plan.monitoring_scope || "Production performance, drift, stability, alerts, owner actions, and revalidation triggers."} />
          <InfoBlock label="Data source reference" value={plan.data_source_ref || "Not defined"} />
          <InfoBlock label="Production start" value={formatDate(plan.production_start_date)} />
          <InfoBlock label="Notes" value={plan.notes || "No monitoring notes recorded."} />
        </div>
      </AtlasCard>

      <AtlasCard eyebrow="Metrics and thresholds" title="Governed monitoring controls">
        {detail.metrics.length ? (
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="min-w-[1280px] w-full text-left text-sm">
              <thead className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
                <tr><th className="px-4 py-3">Metric</th><th className="px-4 py-3">Category</th><th className="px-4 py-3">Definition</th><th className="px-4 py-3">Warning</th><th className="px-4 py-3">Breach</th><th className="px-4 py-3">Lower warning</th><th className="px-4 py-3">Lower breach</th><th className="px-4 py-3">Unit</th><th className="px-4 py-3">Cadence</th><th className="px-4 py-3">Owner</th><th className="px-4 py-3">Status</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {detail.metrics.map((metric) => <MetricRow key={metric.monitoring_metric_id} metric={metric} />)}
              </tbody>
            </table>
          </div>
        ) : <AtlasEmptyState title="No monitoring metrics yet" body="Seed metrics from the workflow template or add custom production metrics before running monitoring." action={<button type="button" className="atlas-primary-button" onClick={() => void execute("seed metrics", () => seedMonitoringMetrics(plan.monitoring_plan_id))}>Seed Template Metrics</button>} />}
      </AtlasCard>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(360px,1.1fr)]">
        <AtlasCard eyebrow="Latest monitoring run" title={latestRun ? latestRun.run_name || latestRun.monitoring_run_id : "No run recorded"}>
          {latestRun ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <InfoBlock label="Run period" value={`${formatDate(latestRun.run_period_start)} to ${formatDate(latestRun.run_period_end)}`} />
              <InfoBlock label="Run status" value={monitoringRunStatusLabels[latestRun.run_status] || humanize(latestRun.run_status)} />
              <InfoBlock label="Overall status" value={humanize(latestRun.overall_status)} />
              <InfoBlock label="Warnings / breaches" value={`${latestRun.warning_count ?? 0} warnings, ${latestRun.breach_count ?? 0} breaches`} />
              <InfoBlock label="Evidence" value={latestRun.evidence_ref || "No evidence reference"} />
              <InfoBlock label="Summary" value={latestRun.summary || "No summary recorded."} />
            </div>
          ) : <AtlasEmptyState title="No monitoring run yet" body="Run monitoring to capture observations, alerts, evidence, and audit history." />}
        </AtlasCard>

        <AtlasCard eyebrow="Trend visuals" title="Metric trend with threshold bands and status markers">
          {trendRows.length ? <MonitoringTrend observations={trendRows} metrics={detail.metrics} /> : <AtlasEmptyState title="No trend data yet" body="Observation trends appear after monitoring runs record metric values." />}
        </AtlasCard>
      </section>

      <AtlasCard eyebrow="Observation table" title="Latest metric observations">
        {detail.observations.length ? (
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="min-w-[1100px] w-full text-left text-sm">
              <thead className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
                <tr><th className="px-4 py-3">Metric</th><th className="px-4 py-3">Observed</th><th className="px-4 py-3">Baseline</th><th className="px-4 py-3">Threshold</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">Interpretation</th><th className="px-4 py-3">Period</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {detail.observations.slice(0, 100).map((observation) => (
                  <tr key={observation.observation_id} className="align-top hover:bg-slate-50">
                    <td className="px-4 py-3 font-semibold text-slate-950">{observation.metric_name}</td>
                    <td className="px-4 py-3 tabular-nums">{formatNumber(observation.observed_value)}</td>
                    <td className="px-4 py-3 tabular-nums">{formatNumber(observation.baseline_value)}</td>
                    <td className="px-4 py-3 text-slate-600">{observation.threshold_used || "Not applied"}</td>
                    <td className="px-4 py-3"><AtlasStatusBadge tone={monitoringStatusTone(observation.status) as any}>{monitoringObservationStatusLabels[observation.status] || humanize(observation.status)}</AtlasStatusBadge></td>
                    <td className="px-4 py-3 text-xs leading-5 text-slate-600">{observation.interpretation}</td>
                    <td className="px-4 py-3 text-xs text-slate-500">{formatDate(observation.period_start)} to {formatDate(observation.period_end)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <AtlasEmptyState title="No observations recorded" body="Observations are persisted when a monitoring run is completed or when metric values are recorded manually." />}
      </AtlasCard>

      <section className="grid gap-4 xl:grid-cols-2">
        <AtlasCard eyebrow="Alerts" title="Open and resolved monitoring alerts">
          {detail.alerts.length ? (
            <div className="space-y-3">
              {detail.alerts.slice(0, 12).map((alert) => <AlertPanel key={alert.alert_id} alert={alert} onAction={execute} />)}
            </div>
          ) : <AtlasEmptyState title="No monitoring alerts" body="Threshold breaches and manual alerts will appear here." />}
        </AtlasCard>

        <AtlasCard eyebrow="Monitoring actions" title="Remediation, owners, and due dates">
          {detail.actions.length ? (
            <div className="space-y-3">
              {detail.actions.map((action) => (
                <div key={action.action_id} className="rounded-xl border border-slate-200 bg-white p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="font-semibold text-slate-950">{action.title}</div>
                      <div className="mt-1 text-sm leading-6 text-slate-600">{action.description}</div>
                    </div>
                    <AtlasStatusBadge tone={monitoringStatusTone(action.status) as any}>{humanize(action.status)}</AtlasStatusBadge>
                  </div>
                  <div className="mt-3 grid gap-2 text-xs text-slate-500 sm:grid-cols-3">
                    <div>Owner: {action.owner_user_id || "Unassigned"}</div>
                    <div>Due: {formatDate(action.due_date)}</div>
                    <div>Type: {humanize(action.action_type)}</div>
                  </div>
                </div>
              ))}
            </div>
          ) : <AtlasEmptyState title="No remediation actions" body="Actions are created from alerts, revalidation reviews, and owner remediation workflows." />}
        </AtlasCard>
      </section>

      <AtlasCard eyebrow="Evidence and documentation" title="Monitoring package mapping">
        <div className="grid gap-3 lg:grid-cols-4">
          <InfoBlock label="Monitoring evidence artifact" value={latestRun?.evidence_ref || "Create a monitoring run to capture evidence"} />
          <InfoBlock label="Documentation mapping" value="Monitoring plan, metric definitions, thresholds, latest run, alerts, remediation, and revalidation decisions" />
          <InfoBlock label="Decision Journal" value="Revalidation reviews and accepted-risk decisions are recorded as decision entries" />
          <InfoBlock label="Sharing" value="Monitoring plans, runs, alerts, and reports are shareable governed resources" />
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <Link to="/model-document-studio" className="atlas-secondary-button">Open Documentation Studio <ArrowRight size={15} /></Link>
          <Link to="/journal" className="atlas-secondary-button">Open Decision Journal <ArrowRight size={15} /></Link>
          <Link to="/model-evidence-center" className="atlas-secondary-button">Open Evidence Center <ArrowRight size={15} /></Link>
        </div>
      </AtlasCard>

      {shareOpen && (
        <ShareResourceDialog
          open={shareOpen}
          resourceType="monitoring_plan"
          resourceId={plan.monitoring_plan_id}
          resourceName={plan.plan_name}
          onClose={() => setShareOpen(false)}
        />
      )}
    </div>
  );
}

function MetricRow({ metric }: { metric: MonitoringMetric }) {
  return (
    <tr className="align-top hover:bg-blue-50/40">
      <td className="px-4 py-3 font-semibold text-slate-950">{metric.metric_name}</td>
      <td className="px-4 py-3 text-slate-700">{metric.metric_category}</td>
      <td className="max-w-sm px-4 py-3 text-xs leading-5 text-slate-600">{metric.metric_definition}</td>
      <td className="px-4 py-3 tabular-nums">{formatNumber(metric.warning_threshold ?? undefined)}</td>
      <td className="px-4 py-3 tabular-nums">{formatNumber(metric.breach_threshold ?? undefined)}</td>
      <td className="px-4 py-3 tabular-nums">{formatNumber(metric.lower_warning_threshold ?? undefined)}</td>
      <td className="px-4 py-3 tabular-nums">{formatNumber(metric.lower_breach_threshold ?? undefined)}</td>
      <td className="px-4 py-3 text-slate-600">{metric.unit || "Value"}</td>
      <td className="px-4 py-3 text-slate-600">{metric.cadence || "Plan cadence"}</td>
      <td className="px-4 py-3 text-slate-600">{metric.owner_user_id || "Plan owner"}</td>
      <td className="px-4 py-3"><AtlasStatusBadge tone={monitoringStatusTone(metric.status) as any}>{humanize(metric.status || "active")}</AtlasStatusBadge></td>
    </tr>
  );
}

function AlertPanel({ alert, onAction }: { alert: MonitoringAlert; onAction: (label: string, action: () => Promise<unknown>) => Promise<void> }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-semibold text-slate-950">{alert.title}</div>
          <div className="mt-1 text-sm leading-6 text-slate-600">{alert.description}</div>
        </div>
        <div className="flex gap-2"><AtlasStatusBadge tone={monitoringStatusTone(alert.severity) as any}>{monitoringSeverityLabels[alert.severity] || humanize(alert.severity)}</AtlasStatusBadge><AtlasStatusBadge tone={monitoringStatusTone(alert.status) as any}>{monitoringAlertStatusLabels[alert.status] || humanize(alert.status)}</AtlasStatusBadge></div>
      </div>
      <div className="mt-3 grid gap-2 text-xs text-slate-500 sm:grid-cols-4">
        <div>Metric: {alert.metric_name || "General"}</div>
        <div>Observed: {formatNumber(alert.observed_value)}</div>
        <div>Owner: {alert.owner_name || alert.owner_user_id || "Unassigned"}</div>
        <div>Created: {formatDate(alert.created_at)}</div>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" className="atlas-secondary-button" onClick={() => void onAction("acknowledge alert", () => acknowledgeMonitoringAlert(alert.alert_id))}>Acknowledge</button>
        <button type="button" className="atlas-secondary-button" onClick={() => void onAction("resolve alert", () => resolveMonitoringAlert(alert.alert_id, "Resolved from Monitoring Plan page."))}>Resolve</button>
        <button type="button" className="atlas-secondary-button" onClick={() => void onAction("accept risk", () => acceptMonitoringRisk(alert.alert_id, "Accepted as monitored risk."))}>Accept Risk</button>
        <button type="button" className="atlas-secondary-button" onClick={() => void onAction("create revalidation review", () => createRevalidationReview(alert.alert_id))}>Create Validation Finding</button>
      </div>
    </div>
  );
}

function MonitoringTrend({ observations, metrics }: { observations: MonitoringObservation[]; metrics: MonitoringMetric[] }) {
  const rows = observations.slice(-18);
  const max = Math.max(1, ...rows.map((row) => Number(row.observed_value) || 0));
  const warning = metrics.find((metric) => metric.metric_name === rows[0]?.metric_name)?.warning_threshold;
  const breach = metrics.find((metric) => metric.metric_name === rows[0]?.metric_name)?.breach_threshold;
  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-2 text-xs font-semibold text-slate-500">
        <span className="inline-flex items-center gap-1"><span className="h-2 w-5 rounded bg-blue-600" /> Observed</span>
        <span className="inline-flex items-center gap-1"><span className="h-2 w-5 rounded bg-amber-400" /> Warning threshold</span>
        <span className="inline-flex items-center gap-1"><span className="h-2 w-5 rounded bg-red-500" /> Breach threshold</span>
      </div>
      <div className="relative h-72 rounded-xl border border-slate-200 bg-gradient-to-b from-slate-50 to-white p-4">
        <div className="absolute left-4 top-3 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Observed value</div>
        <div className="absolute bottom-2 right-4 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Monitoring run order</div>
        {warning != null && <ThresholdLine value={warning} max={max} color="bg-amber-400" label={`Warning ${warning}`} />}
        {breach != null && <ThresholdLine value={breach} max={max} color="bg-red-500" label={`Breach ${breach}`} />}
        <div className="absolute inset-x-6 bottom-8 top-10 flex items-end gap-2">
          {rows.map((row, index) => (
            <div key={`${row.observation_id}-${index}`} className="flex h-full min-w-4 flex-1 items-end">
              <div className={`w-full rounded-t ${row.status === "breach" ? "bg-red-500" : row.status === "warning" ? "bg-amber-400" : "bg-blue-600"}`} style={{ height: `${Math.max(4, ((Number(row.observed_value) || 0) / max) * 100)}%` }} title={`${row.metric_name}: ${formatNumber(row.observed_value)} (${row.status})`} />
            </div>
          ))}
        </div>
      </div>
      <div className="mt-2 text-xs text-slate-500">Threshold annotations and status markers are generated from persisted monitoring observations.</div>
    </div>
  );
}

function ThresholdLine({ value, max, color, label }: { value: number; max: number; color: string; label: string }) {
  const bottom = Math.max(12, Math.min(88, (value / max) * 100));
  return <div className="absolute left-6 right-6" style={{ bottom: `${bottom}%` }}><div className={`h-0.5 ${color}`} /><span className="absolute right-0 -top-5 rounded bg-white px-2 py-0.5 text-[10px] font-semibold text-slate-600 shadow-sm">{label}</span></div>;
}

function InfoBlock({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
      <div className="atlas-eyebrow">{label}</div>
      <div className="mt-1 text-sm font-semibold leading-6 text-slate-950">{value}</div>
    </div>
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

function GaugeIcon() {
  return <Activity size={18} />;
}

function buildTrend(observations: MonitoringObservation[]) {
  const firstMetric = observations[0]?.metric_name;
  return observations.filter((observation) => observation.metric_name === firstMetric);
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

function formatNumber(value?: number | null) {
  return typeof value === "number" ? value.toLocaleString(undefined, { maximumFractionDigits: 4 }) : "Not set";
}

function exportJson(filename: string, payload: unknown) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  downloadBlob(filename, blob);
}

function exportCsv(filename: string, rows: Array<Record<string, unknown>>) {
  const keys = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  const lines = [keys.join(","), ...rows.map((row) => keys.map((key) => JSON.stringify(row[key] ?? "")).join(","))];
  downloadBlob(filename, new Blob([lines.join("\n")], { type: "text/csv" }));
}

function downloadBlob(filename: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
