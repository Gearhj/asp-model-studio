import { useCallback, useEffect, useState } from "react";
import type React from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, CheckCircle2, MessageSquareWarning, Plus, RefreshCw, ShieldCheck } from "lucide-react";
import AtlasCard from "../components/ui/AtlasCard";
import AtlasEmptyState from "../components/ui/AtlasEmptyState";
import AtlasMetricCard from "../components/ui/AtlasMetricCard";
import AtlasPageHero from "../components/ui/AtlasPageHero";
import { RegistryStatus, formatRegistryDate, humanize } from "../components/registry/RegistryPrimitives";
import {
  createValidationApproval,
  createValidationChallenge,
  createValidationFinding,
  createValidationResponse,
  getProjectValidation,
  getValidationCase,
  startValidationReview,
  submitProjectValidation,
  updateValidationChecklist,
  type ValidationDetail,
} from "../lib/validationApi";

export default function ValidationCaseDetail() {
  const { validationId = "", projectId = "" } = useParams();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<ValidationDetail | null>(null);
  const [projectLookup, setProjectLookup] = useState<Record<string, any> | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      if (validationId) {
        setDetail(await getValidationCase(validationId));
      } else if (projectId) {
        const lookup = await getProjectValidation(projectId);
        if (lookup.case?.validation_id) {
          navigate(`/validation/${encodeURIComponent(lookup.case.validation_id)}`, { replace: true });
          return;
        }
        setProjectLookup(lookup);
      }
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "ATLAS could not load validation context.");
    } finally {
      setLoading(false);
    }
  }, [navigate, projectId, validationId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function run(action: () => Promise<ValidationDetail>) {
    setSaving(true);
    setError("");
    try {
      setDetail(await action());
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Validation action failed.");
    } finally {
      setSaving(false);
    }
  }

  if (loading && !detail && !projectLookup) {
    return <div className="atlas-page-shell"><AtlasCard title="Loading validation case"><p className="text-sm text-slate-600">Loading independent validation context...</p></AtlasCard></div>;
  }

  if (!detail && projectLookup) {
    const project = projectLookup.project || {};
    const asset = projectLookup.registry?.asset || {};
    return (
      <div className="atlas-page-shell atlas-theme-analytics" data-testid="project-validation-submit">
        <AtlasPageHero
          dark
          eyebrow="Independent validation intake"
          title="Submit for Validation"
          subtitle="Create a real validation case for this persisted ATLAS asset. No validation record exists until you submit it."
          actions={<Link to="/registry" className="atlas-secondary-button border-white/30 bg-white/10 text-white hover:bg-white/20"><ArrowLeft size={16} /> Registry</Link>}
        />
        {error && <AtlasCard tone="attention" title="Validation intake issue"><p className="text-sm">{error}</p></AtlasCard>}
        <AtlasCard eyebrow="Project ready for intake" title={project.project_name || asset.name || projectId} action={<button type="button" className="atlas-primary-button" disabled={saving} onClick={() => void run(() => submitProjectValidation(projectId, { risk_tier: asset.risk_tier, summary: "Submitted from the project validation intake." }))}>Submit for Validation</button>}>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Info label="Lifecycle" value={<RegistryStatus value={asset.lifecycle_status || "Not recorded"} />} />
            <Info label="Evidence" value={`${asset.evidence_readiness_percent ?? 0}% ${asset.evidence_status ?? ""}`} />
            <Info label="Documentation" value={`${asset.documentation_readiness_percent ?? 0}% ${asset.documentation_status ?? ""}`} />
            <Info label="Validation" value={asset.validation_status || "Not submitted"} />
          </div>
        </AtlasCard>
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="atlas-page-shell">
        <AtlasCard tone="attention" title="Validation case unavailable">
          <p className="text-sm">{error || "The requested validation case was not found."}</p>
          <Link to="/validation" className="atlas-secondary-button mt-4"><ArrowLeft size={16} /> Return to Validation Queue</Link>
        </AtlasCard>
      </div>
    );
  }

  const current = detail.case;
  return (
    <div className="atlas-page-shell atlas-theme-analytics" data-testid="validation-case-detail">
      <AtlasPageHero
        dark
        eyebrow={`${humanize(current.validation_template_id)} | Independent validation`}
        title={detail.project.project_name || current.project_id}
        subtitle={current.summary || "Review evidence, challenge assumptions, document findings, and record independent validation disposition."}
        actions={(
          <>
            <Link to="/validation" className="atlas-secondary-button border-white/30 bg-white/10 text-white hover:bg-white/20"><ArrowLeft size={16} /> Queue</Link>
            <button type="button" className="atlas-secondary-button border-white/30 bg-white/10 text-white hover:bg-white/20" onClick={() => void load()} disabled={loading}><RefreshCw size={16} className={loading ? "animate-spin" : ""} /> Refresh</button>
            {current.status === "submitted" && <button type="button" className="atlas-primary-button bg-white text-slate-950 hover:bg-slate-100" disabled={saving} onClick={() => void run(() => startValidationReview(current.validation_id))}>Start Review</button>}
          </>
        )}
        aside={<div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-white/20 bg-white/15"><HeroFact label="Status" value={current.business_status_label} /><HeroFact label="Findings" value={detail.summary.open_finding_count ?? 0} /><HeroFact label="Checklist" value={`${detail.summary.checklist_passed ?? 0}/${detail.summary.checklist_total ?? 0}`} /><HeroFact label="Next review" value={formatRegistryDate(current.next_review_date)} /></div>}
      />

      {error && <AtlasCard tone="attention" title="Validation action issue"><p className="text-sm">{error}</p></AtlasCard>}

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
        <AtlasMetricCard label="Case status" value={current.business_status_label} icon={<ShieldCheck size={18} />} tone={["approved", "approved_with_conditions"].includes(current.status) ? "success" : "info"} />
        <AtlasMetricCard label="Checklist passed" value={detail.summary.checklist_passed ?? 0} detail={`${detail.summary.checklist_total ?? 0} total`} icon={<CheckCircle2 size={18} />} tone="success" />
        <AtlasMetricCard label="Failed checks" value={detail.summary.checklist_failed ?? 0} tone={(detail.summary.checklist_failed ?? 0) ? "warning" : "neutral"} />
        <AtlasMetricCard label="Open findings" value={detail.summary.open_finding_count ?? 0} tone={(detail.summary.open_finding_count ?? 0) ? "warning" : "success"} />
        <AtlasMetricCard label="Challenges" value={detail.summary.challenge_count ?? 0} icon={<MessageSquareWarning size={18} />} />
        <AtlasMetricCard label="Approvals" value={detail.summary.approval_count ?? 0} />
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1.25fr)_minmax(340px,0.75fr)]">
        <Checklist detail={detail} saving={saving} onSave={(itemKey, payload) => run(() => updateValidationChecklist(current.validation_id, itemKey, payload))} />
        <CaseActions detail={detail} saving={saving} run={run} />
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <Findings detail={detail} saving={saving} run={run} />
        <Challenges detail={detail} saving={saving} run={run} />
      </section>

      <AtlasCard eyebrow="Case history" title="Validation events">
        {detail.events.length ? <div className="divide-y divide-slate-100">{detail.events.map((event) => <div key={event.event_id} className="py-3"><div className="flex justify-between gap-3"><div className="font-semibold text-slate-950">{event.title}</div><div className="text-xs text-slate-500">{formatRegistryDate(event.created_at, true)}</div></div>{event.summary && <p className="mt-1 text-sm text-slate-600">{event.summary}</p>}</div>)}</div> : <AtlasEmptyState title="No validation events yet" body="Submission, review, finding, challenge, response, and approval events will appear here." />}
      </AtlasCard>
    </div>
  );
}

function Checklist({ detail, saving, onSave }: { detail: ValidationDetail; saving: boolean; onSave: (itemKey: string, payload: Record<string, unknown>) => void }) {
  return (
    <AtlasCard eyebrow="Validator checklist" title="Independent review checklist">
      <div className="divide-y divide-slate-100">
        {detail.checklist.map((item) => (
          <div key={item.item_key} className="grid gap-3 py-4 lg:grid-cols-[minmax(0,1fr)_170px_120px] lg:items-center">
            <div><div className="font-semibold text-slate-950">{item.item_label}</div><p className="mt-1 text-xs leading-5 text-slate-600">{item.item_description}</p>{item.reviewer_notes && <p className="mt-2 text-xs font-medium text-blue-800">{item.reviewer_notes}</p>}</div>
            <RegistryStatus value={humanize(item.status)} />
            <button type="button" className="atlas-secondary-button justify-center" disabled={saving} onClick={() => onSave(item.item_key, { status: item.status === "passed" ? "not_reviewed" : "passed", result: item.status === "passed" ? "" : "Validated" })}>{item.status === "passed" ? "Reset" : "Pass"}</button>
          </div>
        ))}
      </div>
    </AtlasCard>
  );
}

function CaseActions({ detail, saving, run }: { detail: ValidationDetail; saving: boolean; run: (action: () => Promise<ValidationDetail>) => void }) {
  const caseId = detail.case.validation_id;
  return (
    <AtlasCard eyebrow="Disposition" title="Approval decision" tone="info">
      <p className="text-sm leading-6 text-blue-950">Record the independent validation disposition only after checklist review, findings, and challenges are resolved or formally accepted as conditions.</p>
      <div className="mt-4 grid gap-2">
        <button type="button" className="atlas-primary-button justify-center" disabled={saving} onClick={() => run(() => createValidationApproval(caseId, { decision: "approved", final_score: 100, decision_rationale: "Validation review approved." }))}>Approve</button>
        <button type="button" className="atlas-secondary-button justify-center" disabled={saving} onClick={() => run(() => createValidationApproval(caseId, { decision: "approved_with_conditions", final_score: 85, decision_rationale: "Approved with documented conditions." }))}>Approve with Conditions</button>
        <button type="button" className="atlas-secondary-button justify-center" disabled={saving} onClick={() => run(() => createValidationApproval(caseId, { decision: "rejected", final_score: 0, decision_rationale: "Validation review rejected the asset." }))}>Reject</button>
      </div>
    </AtlasCard>
  );
}

function Findings({ detail, saving, run }: { detail: ValidationDetail; saving: boolean; run: (action: () => Promise<ValidationDetail>) => void }) {
  const [title, setTitle] = useState("");
  return (
    <AtlasCard eyebrow="Findings" title="Validation findings">
      <div className="flex gap-2">
        <input className="atlas-input" placeholder="Add a finding title" value={title} onChange={(event) => setTitle(event.target.value)} />
        <button type="button" className="atlas-primary-button" disabled={saving || !title.trim()} onClick={() => { const value = title; setTitle(""); run(() => createValidationFinding(detail.case.validation_id, { title: value, severity: "Medium", status: "open", category: "Governance" })); }}><Plus size={15} /> Add</button>
      </div>
      <div className="mt-4 divide-y divide-slate-100">
        {detail.findings.length ? detail.findings.map((finding) => (
          <div key={finding.finding_id} className="py-3"><div className="flex justify-between gap-3"><div className="font-semibold text-slate-950">{finding.title}</div><RegistryStatus value={finding.severity} /></div><div className="mt-1 flex gap-2 text-xs text-slate-500"><RegistryStatus value={humanize(finding.status)} /><span>{finding.remediation_owner || "Owner not assigned"}</span></div>{finding.description && <p className="mt-2 text-sm text-slate-600">{finding.description}</p>}</div>
        )) : <AtlasEmptyState title="No findings recorded" body="Validator findings and required remediation will appear here." />}
      </div>
    </AtlasCard>
  );
}

function Challenges({ detail, saving, run }: { detail: ValidationDetail; saving: boolean; run: (action: () => Promise<ValidationDetail>) => void }) {
  const [title, setTitle] = useState("");
  return (
    <AtlasCard eyebrow="Challenge log" title="Validator challenges">
      <div className="flex gap-2">
        <input className="atlas-input" placeholder="Add a challenge title" value={title} onChange={(event) => setTitle(event.target.value)} />
        <button type="button" className="atlas-primary-button" disabled={saving || !title.trim()} onClick={() => { const value = title; setTitle(""); run(() => createValidationChallenge(detail.case.validation_id, { title: value, challenge_type: "methodology", status: "open" })); }}><Plus size={15} /> Add</button>
      </div>
      <div className="mt-4 divide-y divide-slate-100">
        {detail.challenges.length ? detail.challenges.map((challenge) => (
          <div key={challenge.challenge_id} className="py-3">
            <div className="flex justify-between gap-3"><div className="font-semibold text-slate-950">{challenge.title}</div><RegistryStatus value={humanize(challenge.status)} /></div>
            {challenge.validator_position && <p className="mt-2 text-sm text-slate-600">{challenge.validator_position}</p>}
            <button type="button" className="atlas-secondary-button mt-3" disabled={saving} onClick={() => run(() => createValidationResponse(detail.case.validation_id, challenge.challenge_id, { response_text: "Owner response recorded from the validation case detail page." }))}>Add owner response</button>
            {challenge.responses.length > 0 && <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">{challenge.responses.map((response) => <div key={response.response_id}>{response.responder_name || "Responder"}: {response.response_text}</div>)}</div>}
          </div>
        )) : <AtlasEmptyState title="No challenges recorded" body="Methodology, evidence, implementation, or decision challenges will appear here." />}
      </div>
    </AtlasCard>
  );
}

function Info({ label, value }: { label: string; value: React.ReactNode }) {
  return <div className="rounded-lg border border-slate-200 bg-slate-50 p-4"><div className="atlas-eyebrow">{label}</div><div className="mt-2 text-sm font-semibold text-slate-950">{value}</div></div>;
}

function HeroFact({ label, value }: { label: string; value: React.ReactNode }) {
  return <div className="min-w-0 p-3"><div className="text-[10px] font-semibold uppercase tracking-wide text-white/70">{label}</div><div className="mt-1 truncate text-sm font-semibold text-white">{value}</div></div>;
}
