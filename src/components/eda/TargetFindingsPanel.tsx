// Part J: Target Findings and Evidence.
//
// Replaces the single free-text blob that lived in one unscoped browser key.
// Each finding is a durable record scoped to the immutable
// (project, dataset, version, target) it was written against, so it survives a
// refresh, a different browser, and a different reviewer.
import { useState } from "react";
import { CheckCircle2, FileSearch, LoaderCircle, Plus, Save, Download } from "lucide-react";
import { DRAFT_EXPORT_MARKERS, type TargetFinding } from "../../lib/targetIntelligence";

const SEVERITIES: Array<{ value: TargetFinding["severity"]; label: string }> = [
  { value: "info", label: "Informational" },
  { value: "review", label: "Review recommended" },
  { value: "warning", label: "Warning" },
  { value: "blocker", label: "Blocker" },
];

const SEVERITY_CLASSES: Record<TargetFinding["severity"], string> = {
  info: "border-slate-200 bg-white text-slate-700",
  review: "border-blue-200 bg-blue-50 text-blue-900",
  warning: "border-amber-300 bg-amber-50 text-amber-950",
  blocker: "border-red-300 bg-red-50 text-red-900",
};

const STATUS_LABELS: Record<TargetFinding["status"], string> = {
  open: "Open",
  reviewed: "Reviewed",
  resolved: "Resolved",
};

const SCOPE_BADGE: Record<TargetFinding["scopeMode"], string> = {
  governed_version: "border-emerald-300 bg-emerald-50 text-emerald-900",
  workspace_draft: "border-amber-300 bg-amber-50 text-amber-900",
  legacy_unscoped: "border-slate-300 bg-slate-50 text-slate-700",
};

export default function TargetFindingsPanel({
  findings,
  legacyFindings,
  loading,
  error,
  governed,
  scopeLabel,
  saving,
  message,
  evidenceId,
  evidenceDisabledReason,
  onCreate,
  onUpdate,
  onPromote,
  onSaveEvidence,
  onExportSummary,
  onRegister,
}: {
  findings: TargetFinding[];
  legacyFindings: TargetFinding[];
  loading: boolean;
  error: string | null;
  /** Server-confirmed governed scope. Never derived in this component. */
  governed: boolean;
  scopeLabel: string;
  saving: boolean;
  message: string;
  evidenceId: string | null;
  evidenceDisabledReason?: string;
  onCreate: (input: { title: string; detail: string; severity: TargetFinding["severity"] }) => Promise<void>;
  onUpdate: (findingId: string, input: { title?: string; detail?: string; severity?: TargetFinding["severity"]; status?: TargetFinding["status"] }) => Promise<void>;
  onPromote: (findingId: string) => Promise<void>;
  onSaveEvidence: () => void;
  onExportSummary: () => void;
  onRegister: () => void;
}) {
  const [title, setTitle] = useState("");
  const [detail, setDetail] = useState("");
  const [severity, setSeverity] = useState<TargetFinding["severity"]>("review");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editDetail, setEditDetail] = useState("");

  async function submit() {
    if (!title.trim()) return;
    await onCreate({ title: title.trim(), detail: detail.trim(), severity });
    setTitle("");
    setDetail("");
    setSeverity("review");
  }

  return (
    <div className="space-y-4" data-testid="target-findings-panel">
      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <h3 className="text-sm font-semibold text-slate-900">
          {governed ? "Add Governed Finding" : "Add Draft Finding"}
        </h3>
        <p className="mt-1 text-xs text-slate-600" data-testid="target-finding-scope-note">
          {governed
            ? `Findings are stored against ${scopeLabel}. A finding recorded on one dataset version is never presented as if it applied to another.`
            : `Findings are stored against ${scopeLabel}. A draft finding is NOT stored against an immutable dataset version, and it will not be shown once a different workspace dataset is loaded.`}
        </p>
        <div className="mt-3 grid gap-3 lg:grid-cols-[1.5fr_0.7fr]">
          <input
            type="text"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Finding title"
            maxLength={300}
            data-testid="target-finding-title"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
          <select
            value={severity}
            onChange={(event) => setSeverity(event.target.value as TargetFinding["severity"])}
            data-testid="target-finding-severity"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          >
            {SEVERITIES.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </div>
        <textarea
          value={detail}
          onChange={(event) => setDetail(event.target.value)}
          rows={3}
          maxLength={8000}
          placeholder="What was observed, on which evidence, and what should happen next."
          data-testid="target-finding-detail"
          className="mt-3 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
        />
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            className="atlas-primary-button"
            data-testid="target-finding-save"
            disabled={!title.trim() || saving}
            onClick={() => void submit()}
          >
            {saving ? <LoaderCircle size={15} className="animate-spin" /> : <Plus size={15} />}
            {governed ? "Add Governed Finding" : "Add Draft Finding"}
          </button>
          <button
            type="button"
            className="atlas-secondary-button"
            data-testid="target-save-evidence"
            disabled={saving || !!evidenceDisabledReason}
            aria-describedby={evidenceDisabledReason ? "target-evidence-disabled-reason" : undefined}
            onClick={onSaveEvidence}
          >
            <Save size={15} /> Save Target Analysis to Evidence
          </button>
          <button
            type="button"
            className="atlas-secondary-button"
            data-testid="target-export-summary"
            onClick={onExportSummary}
          >
            <Download size={15} /> {governed ? "Export bounded summary" : "Export draft summary"}
          </button>
          {message ? (
            <span className="text-xs font-semibold text-slate-600" role="status" aria-live="polite" data-testid="target-findings-message">
              {message}
            </span>
          ) : null}
        </div>

        {/* The reason a control is disabled is always visible text, never a
            tooltip -- a governance restriction the user cannot read is not a
            restriction they can act on. */}
        {evidenceDisabledReason ? (
          <div
            id="target-evidence-disabled-reason"
            className="mt-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-950"
            data-testid="target-evidence-disabled-reason"
          >
            <p>{evidenceDisabledReason}</p>
            <button
              type="button"
              className="atlas-secondary-button mt-2"
              data-testid="target-evidence-register-cta"
              onClick={onRegister}
            >
              Register or Link a Dataset Version
            </button>
          </div>
        ) : null}
        {!governed ? (
          <p className="mt-2 text-xs text-amber-900" data-testid="target-draft-export-warning">
            A downloaded draft summary is marked {DRAFT_EXPORT_MARKERS.join(", ")}.
          </p>
        ) : null}
        {evidenceId ? (
          <p className="mt-2 rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-2 text-xs text-emerald-900" data-testid="target-evidence-saved">
            Governed evidence artifact <strong>{evidenceId}</strong> created.
          </p>
        ) : null}
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-900">
            <FileSearch size={15} className="mr-1 inline" /> Recorded target findings
          </h3>
          <span className="text-xs text-slate-500" data-testid="target-finding-count">
            {findings.length.toLocaleString()} recorded
          </span>
        </div>

        {loading ? <p className="mt-3 text-sm text-slate-600">Loading target findings...</p> : null}
        {error ? <p className="mt-3 text-sm text-red-700">{error}</p> : null}
        {!loading && !error && !findings.length ? (
          <p className="mt-3 text-sm text-slate-600" data-testid="target-findings-empty">
            No target findings have been recorded for this dataset version and target.
          </p>
        ) : null}

        <ul className="mt-3 space-y-3">
          {findings.map((finding) => (
            <li
              key={finding.targetFindingId}
              className={`rounded-lg border p-3 ${SEVERITY_CLASSES[finding.severity]}`}
              data-testid="target-finding-item"
              data-finding-status={finding.status}
            >
              {editingId === finding.targetFindingId ? (
                <div className="space-y-2">
                  <input
                    type="text"
                    value={editTitle}
                    onChange={(event) => setEditTitle(event.target.value)}
                    data-testid="target-finding-edit-title"
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  />
                  <textarea
                    value={editDetail}
                    onChange={(event) => setEditDetail(event.target.value)}
                    rows={3}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  />
                  <div className="flex gap-2">
                    <button
                      type="button"
                      className="atlas-primary-button"
                      data-testid="target-finding-edit-apply"
                      onClick={() => {
                        void onUpdate(finding.targetFindingId, { title: editTitle, detail: editDetail });
                        setEditingId(null);
                      }}
                    >
                      Save changes
                    </button>
                    <button type="button" className="atlas-secondary-button" onClick={() => setEditingId(null)}>
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="text-sm font-semibold">{finding.title}</div>
                      {finding.detail ? <p className="mt-1 text-sm">{finding.detail}</p> : null}
                    </div>
                    <span className="shrink-0 rounded-full border border-current px-2 py-0.5 text-[11px] font-semibold">
                      {STATUS_LABELS[finding.status]}
                    </span>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-slate-600">
                    <span
                      className={`rounded-full border px-2 py-0.5 font-semibold ${SCOPE_BADGE[finding.scopeMode]}`}
                      data-testid="target-finding-scope-label"
                      data-scope-mode={finding.scopeMode}
                    >
                      {finding.scopeLabel}
                    </span>
                    {/* Identity is stated honestly per scope: a draft finding
                        never claims a version it does not have. */}
                    <span data-testid="target-finding-identity">
                      {finding.target || "No target"}
                      {finding.scopeMode === "governed_version"
                        ? ` - version ${finding.versionId}`
                        : finding.scopeMode === "workspace_draft"
                          ? " - workspace dataset, not version-pinned"
                          : " - scope unknown (recorded before version pinning)"}
                    </span>
                    <span>Updated {new Date(finding.updatedAt).toLocaleString()}</span>
                    {finding.promotedFromFindingId ? (
                      <span data-testid="target-finding-promoted">Carried forward from a draft finding</span>
                    ) : null}
                  </div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <button
                      type="button"
                      className="atlas-secondary-button"
                      data-testid="target-finding-edit"
                      onClick={() => {
                        setEditingId(finding.targetFindingId);
                        setEditTitle(finding.title);
                        setEditDetail(finding.detail);
                      }}
                    >
                      Edit finding
                    </button>
                    <button
                      type="button"
                      className="atlas-secondary-button"
                      data-testid="target-finding-review"
                      disabled={finding.status !== "open"}
                      onClick={() => void onUpdate(finding.targetFindingId, { status: "reviewed" })}
                    >
                      <CheckCircle2 size={14} /> Mark reviewed
                    </button>
                    <button
                      type="button"
                      className="atlas-secondary-button"
                      data-testid="target-finding-resolve"
                      disabled={finding.status === "resolved"}
                      onClick={() => void onUpdate(finding.targetFindingId, { status: "resolved" })}
                    >
                      Resolve finding
                    </button>
                    {/* Controlled carry-forward: copies the draft onto the
                        governed version. The draft record is left untouched and
                        the copy starts open -- nothing is auto-promoted. */}
                    {governed && finding.scopeMode !== "governed_version" ? (
                      <button
                        type="button"
                        className="atlas-secondary-button"
                        data-testid="target-finding-promote"
                        onClick={() => void onPromote(finding.targetFindingId)}
                      >
                        Copy to governed version
                      </button>
                    ) : null}
                  </div>
                </>
              )}
            </li>
          ))}
        </ul>

        {legacyFindings.length ? (
          <div className="mt-4 rounded-lg border border-slate-300 bg-slate-50 p-3" data-testid="target-legacy-findings">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-600">
              Legacy findings (recorded before version pinning)
            </h4>
            <p className="mt-1 text-xs text-slate-600">
              These findings were recorded before analyses declared their scope. Their dataset version is unknown, so
              they are not presented as governed.
            </p>
            <ul className="mt-2 space-y-2">
              {legacyFindings.map((finding) => (
                <li key={finding.targetFindingId} className="rounded border border-slate-200 bg-white px-3 py-2 text-sm">
                  <span className="mr-2 rounded-full border border-slate-300 bg-slate-50 px-2 py-0.5 text-[11px] font-semibold text-slate-700">
                    {finding.scopeLabel}
                  </span>
                  {finding.title}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </div>
  );
}
