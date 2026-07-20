import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Activity,
  ArrowLeft,
  BookOpenCheck,
  Clock3,
  Download,
  ExternalLink,
  FileArchive,
  FileCheck2,
  FolderOpen,
  History,
  RefreshCw,
  Share2,
  ShieldCheck,
  Workflow,
} from "lucide-react";
import AtlasCard from "../components/ui/AtlasCard";
import AtlasEmptyState from "../components/ui/AtlasEmptyState";
import AtlasMetricCard from "../components/ui/AtlasMetricCard";
import AtlasPageHero from "../components/ui/AtlasPageHero";
import AtlasProgressBar from "../components/ui/AtlasProgressBar";
import ShareResourceDialog from "../components/sharing/ShareResourceDialog";
import { ASSET_TYPE_LABELS, MetricPair, RegistryStatus, TEMPLATE_LABELS, formatRegistryDate, humanize } from "../components/registry/RegistryPrimitives";
import { getRegistryAsset, type RegistryAssetDetail as RegistryAssetDetailType } from "../lib/registryApi";
import { createProjectMonitoringPlan, getProjectMonitoringPlan, monitoringPlanStatusLabels, monitoringStatusTone, type MonitoringPlanDetail } from "../lib/monitoringApi";

export default function RegistryAssetDetail() {
  const { projectId = "" } = useParams();
  const [detail, setDetail] = useState<RegistryAssetDetailType | null>(null);
  const [monitoringDetail, setMonitoringDetail] = useState<MonitoringPlanDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [shareOpen, setShareOpen] = useState(false);

  const load = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    setError("");
    try {
      const [registryPayload, monitoringPayload] = await Promise.all([
        getRegistryAsset(projectId),
        getProjectMonitoringPlan(projectId).catch(() => null),
      ]);
      setDetail(registryPayload);
      setMonitoringDetail(monitoringPayload);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "ATLAS could not load this registry asset.");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading && !detail) return <DetailLoading />;
  if (!detail) {
    return (
      <div className="atlas-page-shell">
        <AtlasCard tone="attention" title="Registry asset unavailable">
          <p className="text-sm leading-6">{error || "The requested project is not present in the ATLAS persistence registry."}</p>
          <Link to="/registry" className="atlas-secondary-button mt-4"><ArrowLeft size={16} /> Return to Registry</Link>
        </AtlasCard>
      </div>
    );
  }

  const { asset } = detail;
  return (
    <div className="atlas-page-shell atlas-theme-analytics" data-testid="registry-asset-detail">
      <AtlasPageHero
        dark
        eyebrow={`${ASSET_TYPE_LABELS[asset.asset_type] ?? humanize(asset.asset_type)} | Registry asset`}
        title={asset.name}
        subtitle={`${humanize(asset.workflow_type)} workflow | ${TEMPLATE_LABELS[asset.template_id ?? ""] ?? humanize(asset.template_id, "General workflow")} | Owned by ${asset.owner_display_name}`}
        actions={(
          <>
            <Link to="/registry" className="atlas-secondary-button border-white/30 bg-white/10 text-white hover:bg-white/20"><ArrowLeft size={16} /> Registry</Link>
            <Link to="/projects/open" className="atlas-primary-button bg-white text-slate-950 hover:bg-slate-100"><FolderOpen size={16} /> Open project</Link>
            <button type="button" className="atlas-secondary-button border-white/30 bg-white/10 text-white hover:bg-white/20" onClick={() => setShareOpen(true)}><Share2 size={16} /> Share Asset</button>
            <button type="button" className="atlas-secondary-button border-white/30 bg-white/10 text-white hover:bg-white/20" onClick={() => void load()} disabled={loading}><RefreshCw size={16} className={loading ? "animate-spin" : ""} /> Refresh</button>
          </>
        )}
        aside={(
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-white/20 bg-white/15">
            <HeroFact label="Lifecycle" value={asset.lifecycle_status} />
            <HeroFact label="Validation" value={asset.validation_status} />
            <HeroFact label="Evidence" value={`${asset.evidence_readiness_percent}% ${asset.evidence_status}`} />
            <HeroFact label="Open actions" value={asset.open_action_count} />
          </div>
        )}
      />

      {error && <AtlasCard tone="warning" title="Refresh did not complete"><p className="text-sm">{error}</p></AtlasCard>}

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-8">
        <AtlasMetricCard label="Workflow" value={`${asset.workflow_completion_percent}%`} detail={humanize(asset.current_step_id, "No current step")} icon={<Workflow size={18} />} tone="info" />
        <AtlasMetricCard label="Evidence" value={`${asset.evidence_readiness_percent}%`} detail={asset.evidence_status} icon={<ShieldCheck size={18} />} tone={asset.evidence_status === "Ready" || asset.evidence_status === "Approved" ? "success" : "warning"} />
        <AtlasMetricCard label="Documentation" value={`${asset.documentation_readiness_percent}%`} detail={asset.documentation_status} icon={<FileCheck2 size={18} />} tone={asset.documentation_status === "Complete" || asset.documentation_status === "Ready" ? "success" : "warning"} />
        <AtlasMetricCard label="Validation" value={asset.validation_score === null ? asset.validation_status : `${asset.validation_score}%`} detail={asset.validation_status} icon={<BookOpenCheck size={18} />} tone={asset.validation_status === "Complete" ? "success" : "warning"} />
        <AtlasMetricCard label="Recommendation" value={asset.recommendation_status} detail="Persisted disposition" tone={asset.recommendation_status === "Recommended" || asset.recommendation_status === "Approved" ? "success" : "warning"} />
        <AtlasMetricCard label="Implementation" value={asset.implementation_status} detail="Accountable execution" tone={asset.implementation_status === "Plan complete" || asset.implementation_status === "Implemented" ? "success" : "warning"} />
        <AtlasMetricCard label="Monitoring" value={asset.monitoring_status} detail="Post-decision controls" tone={asset.monitoring_status === "Active" || asset.monitoring_status === "Plan complete" ? "success" : "warning"} />
        <AtlasMetricCard label="Findings" value={asset.open_finding_count} detail={`${asset.open_action_count} open actions`} tone={asset.open_finding_count || asset.open_action_count ? "warning" : "success"} />
      </section>

      <AtlasCard
        eyebrow="Production control"
        title="Monitoring Plan"
        tone={monitoringDetail ? "success" : "info"}
        action={monitoringDetail ? <Link to={`/project-monitoring/${encodeURIComponent(asset.project_id)}`} className="atlas-primary-button">Open Monitoring Plan</Link> : undefined}
      >
        {monitoringDetail ? (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            <CountStat label="Plan status" value={monitoringPlanStatusLabels[monitoringDetail.plan.plan_status] || humanize(monitoringDetail.plan.plan_status)} />
            <CountStat label="Owner" value={monitoringDetail.plan.monitoring_owner_name || "Unassigned"} />
            <CountStat label="Cadence" value={monitoringDetail.plan.monitoring_cadence || "Not set"} />
            <CountStat label="Open alerts" value={monitoringDetail.alerts.filter((alert) => !["resolved", "closed", "accepted_risk"].includes(alert.status)).length} />
            <CountStat label="Next run" value={formatRegistryDate(monitoringDetail.plan.next_monitoring_date)} />
          </div>
        ) : (
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
            <p className="text-sm leading-6 text-slate-600">No production monitoring plan exists for this registry asset. Create one when the asset is ready for implementation, launch, or ongoing management review.</p>
            <button
              type="button"
              className="atlas-primary-button justify-center"
              onClick={async () => setMonitoringDetail(await createProjectMonitoringPlan(asset.project_id, { workflow_type: asset.workflow_type, plan_name: `${asset.name} Monitoring Plan` }))}
            >
              Create Monitoring Plan
            </button>
          </div>
        )}
        {monitoringDetail && (
          <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-slate-200 pt-4 text-xs text-slate-500">
            <RegistryStatus value={asset.monitoring_status} />
            <span className="font-semibold text-slate-700">{monitoringDetail.metrics.length} threshold metrics</span>
            <span className={`rounded-full px-2 py-1 font-semibold ${monitoringStatusTone(monitoringDetail.plan.plan_status) === "success" ? "bg-emerald-50 text-emerald-700" : "bg-blue-50 text-blue-700"}`}>Persisted in Monitoring Center</span>
          </div>
        )}
      </AtlasCard>

      <AtlasCard
        eyebrow="Independent validation"
        title="Validation & Challenge Center"
        tone={asset.validation_status === "Approved by validation" || asset.validation_status === "Approved with conditions" ? "success" : "info"}
        action={<Link to={`/project-validation/${encodeURIComponent(asset.project_id)}`} className="atlas-primary-button">{asset.validation_status === "Not submitted" ? "Submit for Validation" : "Open validation case"}</Link>}
      >
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <CountStat label="Validation status" value={asset.validation_status} />
          <CountStat label="Validation score" value={asset.validation_score == null ? "Not scored" : `${asset.validation_score}%`} />
          <CountStat label="Open findings" value={asset.open_finding_count} />
          <CountStat label="Next review" value={formatRegistryDate(asset.next_review_date)} />
          <CountStat label="Lifecycle" value={asset.lifecycle_status} />
        </div>
        <p className="mt-4 text-sm leading-6 text-slate-600">Independent validation records, checklist results, challenges, owner responses, and approval decisions are stored in SQLite and reflected in the registry lifecycle.</p>
      </AtlasCard>

      <section className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1.25fr)_minmax(340px,0.75fr)]">
        <AtlasCard eyebrow="Registry profile" title="Asset summary">
          <div className="grid gap-x-8 sm:grid-cols-2 xl:grid-cols-3">
            <MetricPair label="Registry ID" value={asset.registry_id} valueClassName="font-mono text-xs" />
            <MetricPair label="Project ID" value={asset.project_id} valueClassName="font-mono text-xs" />
            <MetricPair label="Owner" value={asset.owner_display_name} />
            <MetricPair label="Asset type" value={ASSET_TYPE_LABELS[asset.asset_type] ?? humanize(asset.asset_type)} />
            <MetricPair label="Workflow" value={humanize(asset.workflow_type)} />
            <MetricPair label="Template" value={TEMPLATE_LABELS[asset.template_id ?? ""] ?? humanize(asset.template_id, "General workflow")} />
            <MetricPair label="Risk tier" value={asset.risk_tier} />
            <MetricPair label="Created" value={formatRegistryDate(asset.created_at, true)} />
            <MetricPair label="Last activity" value={formatRegistryDate(asset.last_activity_at, true)} />
          </div>
          <div className="mt-4 grid gap-4 border-t border-slate-200 pt-4 lg:grid-cols-2">
            <div><div className="atlas-eyebrow">Business purpose</div><p className="mt-2 text-sm leading-6 text-slate-700">{asset.business_purpose}</p></div>
            <div><div className="atlas-eyebrow">Intended use</div><p className="mt-2 text-sm leading-6 text-slate-700">{asset.intended_use}</p></div>
          </div>
          {asset.tags.length > 0 && <div className="mt-4 flex flex-wrap gap-2 border-t border-slate-200 pt-4">{asset.tags.map((tag) => <span key={tag} className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600">{humanize(tag)}</span>)}</div>}
        </AtlasCard>

        <AtlasCard eyebrow="Access control" title="Asset access panel" tone="info" action={<button type="button" className="atlas-primary-button" onClick={() => setShareOpen(true)}><Share2 size={15} /> Share Asset</button>}>
          <div className="grid gap-3">
            <CountStat label="Owner" value={asset.owner_display_name} />
            <CountStat label="Current user permission" value="Owner, admin, or shared access" />
            <CountStat label="Shared users/groups" value="Open share dialog" />
            <CountStat label="Access history" value="Audit Log" />
          </div>
          <p className="mt-3 text-sm leading-6 text-blue-900">Registry asset sharing uses persisted resource permissions. Admins and owners can grant view, edit, validate, approve, export, or admin access.</p>
        </AtlasCard>

        <AtlasCard eyebrow="Explainable status" title="Lifecycle derivation" tone="info">
          <RegistryStatus value={asset.lifecycle_status} />
          <p className="mt-4 text-sm font-semibold leading-6 text-blue-950">{detail.lifecycle_derivation.matched_rule}</p>
          <ul className="mt-3 grid gap-2 text-xs leading-5 text-blue-900">
            {detail.lifecycle_derivation.reasons.map((reason) => <li key={reason} className="flex gap-2"><span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-600" />{reason}</li>)}
          </ul>
          <div className="mt-5 border-t border-blue-200 pt-4">
            <div className="atlas-eyebrow text-blue-700">Next review</div>
            <div className="mt-1 text-sm font-semibold text-blue-950">{formatRegistryDate(asset.next_review_date)}</div>
          </div>
        </AtlasCard>
      </section>

      <AtlasCard eyebrow="Lifecycle history" title="Persisted asset timeline" action={<span className="inline-flex min-w-0 items-center gap-2 text-xs font-semibold text-slate-500"><History size={14} /> Latest 100 events</span>}>
        {detail.lifecycle_timeline.length ? (
          <div className="max-w-full overflow-x-auto pb-2">
            <ol className="grid gap-3 sm:flex sm:min-w-max sm:gap-0">
              {[...detail.lifecycle_timeline].reverse().map((event, index) => (
                <li key={`${event.event_type}-${event.source_id}-${index}`} className="relative w-full rounded-lg border border-blue-100 bg-white px-4 py-4 sm:w-64 sm:shrink-0 sm:rounded-none sm:border-x-0 sm:border-b-0 sm:border-t-2 sm:bg-transparent sm:pt-5 sm:first:pl-0 sm:last:pr-0">
                  <span className="absolute -top-2 left-4 h-3.5 w-3.5 rounded-full border-2 border-white bg-blue-600 shadow first:left-0" />
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{formatRegistryDate(event.occurred_at)}</div>
                  <div className="mt-2 text-sm font-semibold text-slate-950">{event.title}</div>
                  <p className="mt-1 line-clamp-3 text-xs leading-5 text-slate-600">{event.summary || humanize(event.event_type)}</p>
                  <div className="mt-2 flex items-center gap-2"><RegistryStatus value={event.status || "Recorded"} /><span className="text-[11px] text-slate-500">{event.user_display_name}</span></div>
                </li>
              ))}
            </ol>
          </div>
        ) : <AtlasEmptyState title="No lifecycle events persisted" body="Project, workflow, run, evidence, decision, documentation, export, and audit events will appear here." />}
      </AtlasCard>

      <section className="grid min-w-0 gap-4 xl:grid-cols-2">
        <AtlasCard eyebrow="Governed evidence" title="Evidence readiness" action={<Link to="/model-evidence-center" className="atlas-tertiary-button"><ShieldCheck size={15} /> Evidence Center</Link>}>
          <ReadinessHeader status={detail.evidence_summary.display_status} score={detail.evidence_summary.coverage_score} />
          <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <CountStat label="Required" value={detail.evidence_summary.required_count} />
            <CountStat label="Ready" value={detail.evidence_summary.ready_count} />
            <CountStat label="Approved" value={detail.evidence_summary.approved_count} />
            <CountStat label="Stale / rejected" value={detail.evidence_summary.stale_count + detail.evidence_summary.rejected_count} />
          </div>
          {detail.evidence_summary.missing_required_types.length ? (
            <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-4">
              <div className="text-sm font-semibold text-amber-950">Missing required artifacts</div>
              <div className="mt-2 flex flex-wrap gap-2">{detail.evidence_summary.missing_required_types.map((type) => <span key={type} className="rounded bg-white px-2 py-1 text-xs font-medium text-amber-900 ring-1 ring-amber-200">{humanize(type)}</span>)}</div>
            </div>
          ) : <p className="mt-4 text-sm font-medium text-emerald-800">All required artifact types are present at a ready or approved status.</p>}
        </AtlasCard>

        <AtlasCard eyebrow="Governed documentation" title="Documentation readiness" action={<Link to="/model-document-studio" className="atlas-tertiary-button"><BookOpenCheck size={15} /> Documentation Studio</Link>}>
          <ReadinessHeader status={detail.documentation_summary.display_status} score={detail.documentation_summary.readiness_score} />
          <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <CountStat label="Sections" value={detail.documentation_summary.section_count} />
            <CountStat label="Completed" value={detail.documentation_summary.completed_section_count} />
            <CountStat label="Package" value={humanize(detail.documentation_summary.package_type, "Not created")} />
            <CountStat label="Updated" value={formatRegistryDate(detail.documentation_summary.updated_at)} />
          </div>
          <div className="mt-4 flex items-center gap-3 border-t border-slate-200 pt-4">
            <RegistryStatus value={detail.documentation_summary.package_status || "Not started"} />
            <span className="text-xs text-slate-500">Package ID: {detail.documentation_summary.package_id || "Not created"}</span>
          </div>
        </AtlasCard>
      </section>

      <AtlasCard eyebrow="Execution record" title="Latest analytical runs" action={<span className="inline-flex items-center gap-2 text-xs font-semibold text-slate-500"><Activity size={14} /> {detail.latest_runs.length} persisted</span>}>
        {detail.latest_runs.length ? (
          <>
            <div className="grid gap-3 md:hidden">
              {detail.latest_runs.map((run) => (
                <div key={run.run_id} className="rounded-lg border border-slate-200 bg-white p-4">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <div className="font-semibold text-slate-950">{humanize(run.run_type)}</div>
                      <div className="mt-1 break-all font-mono text-[11px] text-slate-500">{run.run_id}</div>
                    </div>
                    <RegistryStatus value={run.has_error ? "Failed" : run.status} />
                  </div>
                  <div className="mt-3 text-xs text-slate-600">{formatRegistryDate(run.completed_at || run.started_at, true)}</div>
                  <div className="mt-3 flex flex-wrap gap-2">{Object.entries(run.metrics).map(([key, value]) => <span key={key} className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-700"><strong>{humanize(key)}:</strong> {formatMetric(value)}</span>)}</div>
                </div>
              ))}
            </div>
            <div className="hidden overflow-x-auto rounded-lg border border-slate-200 md:block">
              <table className="min-w-[720px] w-full border-collapse text-left text-sm">
                <thead className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500"><tr><th className="px-4 py-3">Run</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">Completed</th><th className="px-4 py-3">Metrics</th></tr></thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {detail.latest_runs.map((run) => (
                    <tr key={run.run_id} className="align-top hover:bg-blue-50/40">
                      <td className="px-4 py-3"><div className="font-semibold text-slate-950">{humanize(run.run_type)}</div><div className="mt-1 font-mono text-[11px] text-slate-500">{run.run_id}</div></td>
                      <td className="px-4 py-3"><RegistryStatus value={run.has_error ? "Failed" : run.status} /></td>
                      <td className="px-4 py-3 text-xs text-slate-600">{formatRegistryDate(run.completed_at || run.started_at, true)}</td>
                      <td className="px-4 py-3"><div className="flex max-w-3xl flex-wrap gap-2">{Object.entries(run.metrics).map(([key, value]) => <span key={key} className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-700"><strong>{humanize(key)}:</strong> {formatMetric(value)}</span>)}</div></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : <AtlasEmptyState title="No analytical runs persisted" body="Completed solver, model, validation, scenario, and monitoring runs will appear here." />}
      </AtlasCard>

      <section className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <AtlasCard eyebrow="Decision accountability" title="Recommendation and implementation">
          <div className="grid gap-x-8 sm:grid-cols-2">
            <MetricPair label="Recommendation" value={<RegistryStatus value={asset.recommendation_status} />} />
            <MetricPair label="Implementation" value={<RegistryStatus value={asset.implementation_status} />} />
            <MetricPair label="Monitoring" value={<RegistryStatus value={asset.monitoring_status} />} />
            <MetricPair label="Latest run" value={<RegistryStatus value={asset.latest_run_status} />} />
          </div>
          {detail.decisions.length ? (
            <div className="mt-4 border-t border-slate-200 pt-4">
              <div className="atlas-eyebrow">Latest decision records</div>
              <div className="mt-2 divide-y divide-slate-100">
                {detail.decisions.slice(0, 6).map((decision) => (
                  <div key={decision.decision_id} className="py-3">
                    <div className="flex flex-wrap items-start justify-between gap-2"><div className="font-semibold text-slate-950">{decision.title}</div><RegistryStatus value={decision.status} /></div>
                    {decision.summary && <p className="mt-1 text-xs leading-5 text-slate-600">{decision.summary}</p>}
                    <div className="mt-1 text-[11px] text-slate-500">{decision.owner || "Owner not recorded"} | {formatRegistryDate(decision.updated_at, true)}</div>
                  </div>
                ))}
              </div>
            </div>
          ) : <AtlasEmptyState title="No recommendation decisions persisted" body="Governance and implementation decisions will appear after they are recorded." />}
        </AtlasCard>

        <AtlasCard eyebrow="Governed delivery" title="Export artifacts" action={<Link to="/exports" className="atlas-tertiary-button"><FileArchive size={15} /> Project exports</Link>}>
          {detail.exports.length ? (
            <>
              <div className="grid gap-3 md:hidden">
                {detail.exports.map((item) => (
                  <div key={item.export_id} className="rounded-lg border border-slate-200 bg-white p-4">
                    <div className="flex items-start gap-2 font-semibold text-slate-950"><Download size={14} className="mt-0.5 shrink-0 text-blue-600" /> <span className="break-all">{item.file_name}</span></div>
                    <div className="mt-2 break-all font-mono text-[11px] text-slate-500">{item.artifact_hash || item.export_id}</div>
                    <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
                      <MetricPair label="Type" value={humanize(item.export_type)} />
                      <MetricPair label="Storage" value={humanize(item.storage_mode)} />
                      <MetricPair label="Generated" value={formatRegistryDate(item.created_at, true)} />
                    </div>
                  </div>
                ))}
              </div>
              <div className="hidden overflow-x-auto md:block">
                <table className="min-w-[560px] w-full border-collapse text-left text-sm">
                  <thead className="border-b border-slate-200 text-[11px] uppercase tracking-wide text-slate-500"><tr><th className="pb-3 pr-4">Artifact</th><th className="pb-3 px-3">Type</th><th className="pb-3 px-3">Storage</th><th className="pb-3 pl-3">Generated</th></tr></thead>
                  <tbody className="divide-y divide-slate-100">
                    {detail.exports.map((item) => (
                      <tr key={item.export_id} className="hover:bg-slate-50">
                        <td className="py-3 pr-4"><div className="flex items-center gap-2 font-semibold text-slate-950"><Download size={14} className="text-blue-600" /> {item.file_name}</div><div className="mt-1 font-mono text-[11px] text-slate-500">{item.artifact_hash || item.export_id}</div></td>
                        <td className="px-3 py-3 text-slate-700">{humanize(item.export_type)}</td>
                        <td className="px-3 py-3 text-slate-700">{humanize(item.storage_mode)}</td>
                        <td className="py-3 pl-3 text-xs text-slate-600">{formatRegistryDate(item.created_at, true)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : <AtlasEmptyState title="No governed exports persisted" body="Reports, JSON manifests, model outputs, and reproducibility code will appear here after export." />}
        </AtlasCard>
      </section>

      {detail.open_actions.length > 0 && (
        <AtlasCard eyebrow="Required attention" title="Open governance actions" tone="warning">
          <div className="grid gap-3 lg:grid-cols-2">
            {detail.open_actions.map((action) => (
              <div key={action.action_id} className="rounded-lg border border-amber-200 bg-white p-4">
                <div className="flex items-start justify-between gap-3"><div className="font-semibold text-slate-950">{action.title}</div><RegistryStatus value={action.severity} /></div>
                <p className="mt-2 text-sm leading-6 text-slate-600">{action.description}</p>
                <div className="mt-3 text-xs font-semibold text-amber-900">{action.recommended_next_step}</div>
              </div>
            ))}
          </div>
        </AtlasCard>
      )}

      <AtlasCard eyebrow="Control record" title="Recent audit trail" action={<Link to="/audit" className="atlas-tertiary-button"><History size={15} /> Full audit log</Link>}>
        {detail.audit_trail.length ? (
          <div className="divide-y divide-slate-100">
            {detail.audit_trail.slice(0, 20).map((event) => (
              <div key={event.audit_id} className="grid gap-2 py-3 first:pt-0 last:pb-0 sm:grid-cols-[180px_minmax(0,1fr)_180px] sm:items-start">
                <div className="flex items-center gap-2 text-xs font-semibold text-slate-600"><Clock3 size={14} /> {formatRegistryDate(event.created_at, true)}</div>
                <div><div className="font-semibold text-slate-950">{event.title || humanize(event.action_type)}</div>{event.summary && <div className="mt-1 text-xs leading-5 text-slate-600">{event.summary}</div>}</div>
                <div className="text-xs text-slate-500 sm:text-right">{event.user_display_name}<div className="mt-1">{humanize(event.entity_type)}</div></div>
              </div>
            ))}
          </div>
        ) : <AtlasEmptyState title="No audit events persisted" body="Backend audit records for this asset will appear here." />}
      </AtlasCard>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-4">
        <Link to="/registry" className="atlas-secondary-button"><ArrowLeft size={16} /> Back to Registry</Link>
        <div className="flex flex-wrap gap-2">
          <Link to="/project-overview" className="atlas-secondary-button">Project Overview <ExternalLink size={15} /></Link>
          <Link to="/projects/open" className="atlas-primary-button"><FolderOpen size={16} /> Open project workflow</Link>
        </div>
      </div>
      <ShareResourceDialog open={shareOpen} onClose={() => setShareOpen(false)} resourceType="registry_asset" resourceId={asset.project_id} resourceName={asset.name} />
    </div>
  );
}

function ReadinessHeader({ status, score }: { status: string; score: number }) {
  return (
    <div>
      <div className="flex items-center justify-between gap-3"><RegistryStatus value={status} /><div className="text-2xl font-semibold tabular-nums text-slate-950">{score}%</div></div>
      <AtlasProgressBar value={score} className="mt-3" />
    </div>
  );
}

function CountStat({ label, value }: { label: string; value: string | number }) {
  return <div className="rounded-lg border border-slate-200 bg-slate-50 p-3"><div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div><div className="mt-1 break-words text-sm font-semibold text-slate-950">{value}</div></div>;
}

function HeroFact({ label, value }: { label: string; value: string | number }) {
  return <div className="min-h-[58px] min-w-0 bg-slate-950/35 p-3"><div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-sky-200">{label}</div><div className="mt-1 break-words text-xs font-semibold leading-4 text-white" title={String(value)}>{value}</div></div>;
}

function formatMetric(value: unknown) {
  if (typeof value === "number") return Number.isInteger(value) ? value.toLocaleString() : value.toLocaleString(undefined, { maximumFractionDigits: 4 });
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (value === null || value === undefined || value === "") return "Not recorded";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function DetailLoading() {
  return (
    <div className="atlas-page-shell" aria-label="Loading registry asset">
      <div className="h-64 animate-pulse rounded-lg bg-slate-900" />
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{Array.from({ length: 8 }, (_, index) => <div key={index} className="h-28 animate-pulse rounded-lg border border-slate-200 bg-white" />)}</div>
      <div className="h-96 animate-pulse rounded-lg border border-slate-200 bg-white" />
    </div>
  );
}
