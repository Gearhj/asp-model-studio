import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, CheckCircle2, ClipboardCheck, RefreshCw, ShieldCheck, TriangleAlert } from "lucide-react";
import AtlasCard from "../components/ui/AtlasCard";
import AtlasEmptyState from "../components/ui/AtlasEmptyState";
import AtlasMetricCard from "../components/ui/AtlasMetricCard";
import AtlasPageHero from "../components/ui/AtlasPageHero";
import { RegistryStatus, formatRegistryDate, humanize } from "../components/registry/RegistryPrimitives";
import { getValidationQueue, getValidationSummary, type ValidationCase, type ValidationSummary } from "../lib/validationApi";

export default function ValidationQueue() {
  const [cases, setCases] = useState<ValidationCase[]>([]);
  const [summary, setSummary] = useState<ValidationSummary | null>(null);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [queue, nextSummary] = await Promise.all([
        getValidationQueue({ status: status || undefined, limit: 500 }),
        getValidationSummary(),
      ]);
      setCases(queue.cases);
      setSummary(nextSummary);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "ATLAS could not load the validation queue.");
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="atlas-page-shell atlas-theme-analytics" data-testid="validation-queue">
      <AtlasPageHero
        dark
        eyebrow="Independent governance review"
        title="Validation & Challenge Center"
        subtitle="Queue, review, challenge, approve, return, and evidence independent validation for governed ATLAS assets."
        actions={<button type="button" className="atlas-secondary-button border-white/30 bg-white/10 text-white hover:bg-white/20" onClick={() => void load()}><RefreshCw size={16} className={loading ? "animate-spin" : ""} /> Refresh queue</button>}
        aside={<div className="rounded-lg border border-white/20 bg-white/10 p-4 text-sm text-white">Validation cases are created only when a user submits a project. No sample cases are created by default.</div>}
      />

      {error && <AtlasCard tone="attention" title="Validation queue unavailable"><p className="text-sm">{error}</p></AtlasCard>}

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
        <AtlasMetricCard label="Cases" value={summary?.total_cases ?? 0} detail="Submitted records" icon={<ClipboardCheck size={18} />} />
        <AtlasMetricCard label="Submitted" value={summary?.submitted ?? 0} detail="Awaiting validator" tone="warning" />
        <AtlasMetricCard label="In review" value={summary?.in_review ?? 0} detail="Active validation" tone="info" icon={<ShieldCheck size={18} />} />
        <AtlasMetricCard label="Returned" value={summary?.returned ?? 0} detail="Owner action" tone={(summary?.returned ?? 0) ? "warning" : "neutral"} />
        <AtlasMetricCard label="Approved" value={summary?.approved ?? 0} detail="Validation disposition" tone="success" icon={<CheckCircle2 size={18} />} />
        <AtlasMetricCard label="Open findings" value={summary?.open_findings ?? 0} detail="Requires closure" tone={(summary?.open_findings ?? 0) ? "warning" : "success"} icon={<TriangleAlert size={18} />} />
      </section>

      <AtlasCard eyebrow="Validation intake" title="Queue">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <label className="grid gap-1 text-sm font-semibold text-slate-700">
            Status filter
            <select className="atlas-input min-w-64" value={status} onChange={(event) => setStatus(event.target.value)}>
              <option value="">All validation statuses</option>
              {["submitted", "in_review", "returned", "remediation", "approved", "approved_with_conditions", "rejected", "withdrawn"].map((option) => (
                <option key={option} value={option}>{humanize(option)}</option>
              ))}
            </select>
          </label>
          <Link to="/registry" className="atlas-secondary-button">Find an asset to submit <ArrowRight size={15} /></Link>
        </div>
        {loading && !cases.length ? (
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-6 text-sm font-semibold text-slate-600">Loading validation cases...</div>
        ) : cases.length ? (
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="min-w-[980px] w-full border-collapse text-left text-sm">
              <thead className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
                <tr><th className="px-4 py-3">Project</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">Validator</th><th className="px-4 py-3">Risk</th><th className="px-4 py-3">Findings</th><th className="px-4 py-3">Submitted</th><th className="px-4 py-3 text-right">Action</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {cases.map((item) => (
                  <tr key={item.validation_id} className="align-top hover:bg-blue-50/50">
                    <td className="px-4 py-3"><div className="font-semibold text-slate-950">{item.project_name || item.project_id}</div><div className="mt-1 font-mono text-[11px] text-slate-500">{item.validation_id}</div></td>
                    <td className="px-4 py-3"><RegistryStatus value={item.business_status_label || humanize(item.status)} /></td>
                    <td className="px-4 py-3 text-slate-700">{item.assigned_validator_name || item.assigned_validator_user_id || "Unassigned"}</td>
                    <td className="px-4 py-3 text-slate-700">{item.risk_tier || "Not classified"}</td>
                    <td className="px-4 py-3"><RegistryStatus value={`${item.open_finding_count ?? 0} open`} /></td>
                    <td className="px-4 py-3 text-xs text-slate-600">{formatRegistryDate(item.submitted_at, true)}</td>
                    <td className="px-4 py-3 text-right"><Link to={`/validation/${encodeURIComponent(item.validation_id)}`} className="atlas-primary-button justify-center">Open case <ArrowRight size={15} /></Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <AtlasEmptyState title="No validation cases submitted" body="Use Project Overview or Registry Asset Detail to submit a real persisted asset for independent validation." action={<Link to="/registry" className="atlas-secondary-button">Open Registry</Link>} />
        )}
      </AtlasCard>
    </div>
  );
}
