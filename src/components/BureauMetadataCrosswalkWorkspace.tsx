import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  FileClock,
  Link2,
  Loader2,
  RefreshCw,
  Save,
  ShieldCheck,
} from "lucide-react";
import {
  BUREAU_CROSSWALK_STATES,
  BureauMetadataRequestError,
  getBureauMetadataCrosswalkHistory,
  getCurrentBureauMetadataCrosswalk,
  previewBureauMetadataCrosswalk,
  retryBureauMetadataCrosswalkBinding,
  saveBureauMetadataCrosswalkDecisions,
  type BureauCrosswalkCandidate,
  type BureauCrosswalkDecision,
  type BureauCrosswalkDecisionInput,
  type BureauCrosswalkGovernance,
  type BureauCrosswalkHistory,
  type BureauCrosswalkPreview,
  type BureauCrosswalkState,
  type BureauCrosswalkStateCounts,
} from "../lib/bureauMetadata";
import type { CanonicalDatasetIdentity } from "../lib/datasetIdentity";

type BureauMetadataCrosswalkWorkspaceProps = {
  projectId: string;
  datasetIdentity: CanonicalDatasetIdentity;
  bindingRevision: number;
  bindingCurrent: boolean;
  onBindingRevisionChanged?: (input: {
    bindingRevision: number;
    crosswalkId: string;
    crosswalkRevision: number;
  }) => void;
};

type ActionState = "load" | "preview" | "save" | "confirm" | "retry" | "history" | null;

type DecisionDraft = BureauCrosswalkDecisionInput;

const TERMINAL_STATES = new Set<BureauCrosswalkState>([
  "exact_verified",
  "approved_alias",
  "transformed_or_derived",
  "out_of_catalog",
  "rejected",
]);

const STATE_LABELS: Record<BureauCrosswalkState, string> = {
  exact_verified: "Exact verified",
  approved_alias: "Approved alias",
  transformed_or_derived: "Transformed / derived",
  probable_review_required: "Probable — review required",
  ambiguous_review_required: "Ambiguous — review required",
  recoding_evidence_required: "Recoding evidence required",
  unresolved: "Unresolved",
  out_of_catalog: "Out of catalog",
  rejected: "Rejected",
};

const STATE_TONES: Record<BureauCrosswalkState, string> = {
  exact_verified: "border-emerald-200 bg-emerald-50 text-emerald-800",
  approved_alias: "border-teal-200 bg-teal-50 text-teal-800",
  transformed_or_derived: "border-indigo-200 bg-indigo-50 text-indigo-800",
  probable_review_required: "border-amber-200 bg-amber-50 text-amber-800",
  ambiguous_review_required: "border-orange-200 bg-orange-50 text-orange-800",
  recoding_evidence_required: "border-fuchsia-200 bg-fuchsia-50 text-fuchsia-800",
  unresolved: "border-rose-200 bg-rose-50 text-rose-800",
  out_of_catalog: "border-slate-300 bg-slate-100 text-slate-700",
  rejected: "border-red-200 bg-red-50 text-red-800",
};

function safeError(error: unknown): BureauMetadataRequestError {
  return error instanceof BureauMetadataRequestError
    ? error
    : new BureauMetadataRequestError({
        status: 0,
        code: "bureau_crosswalk_action_unavailable",
        kind: "unavailable",
        message: "ATLAS could not complete the governed crosswalk action.",
        recovery: "Refresh the bounded workspace. No dataset or modeling authority was changed.",
      });
}

function draftFromDecision(decision: BureauCrosswalkDecision): DecisionDraft {
  return {
    datasetField: decision.datasetField,
    mappingState: decision.mappingState,
    candidateAttributeCode: decision.candidateAttributeCode,
    alternativeAttributeCodes: decision.alternativeAttributeCodes,
    sourceAttributeCodes: decision.sourceAttributeCodes,
    rationale: decision.rationale,
    aliasAuthorityId: decision.aliasAuthorityId,
    institutionalAliasReference: decision.institutionalAliasReference,
    transformationReferenceId: decision.transformationReferenceId,
    transformationRule: decision.transformationRule,
    transformationOrRecodingConcerns: decision.transformationOrRecodingConcerns,
    dataType: decision.dataType,
    units: decision.units,
    sourceSystem: decision.sourceSystem,
    timing: decision.timing,
    specialValueHandling: decision.specialValueHandling,
    valueRangeReconciliation: decision.valueRangeReconciliation,
    specialValueReconciliation: decision.specialValueReconciliation,
  };
}

function countDraftStates(decisions: readonly DecisionDraft[]): BureauCrosswalkStateCounts {
  const counts = Object.fromEntries(BUREAU_CROSSWALK_STATES.map((state) => [state, 0])) as BureauCrosswalkStateCounts;
  for (const decision of decisions) counts[decision.mappingState] += 1;
  return counts;
}

function csvList(value?: string): string[] {
  return Array.from(new Set((value ?? "").split(",").map((item) => item.trim()).filter(Boolean))).slice(0, 32);
}

function candidateCodes(candidates: readonly BureauCrosswalkCandidate[]): string[] {
  return Array.from(
    new Set(
      candidates.flatMap((candidate) => [
        ...(candidate.candidateAttributeCode ? [candidate.candidateAttributeCode] : []),
        ...candidate.alternatives,
      ]),
    ),
  ).sort((left, right) => left.localeCompare(right));
}

function decisionIssue(decision: DecisionDraft): string | null {
  const rationale = decision.rationale?.trim() ?? "";
  const candidate = decision.candidateAttributeCode?.trim() ?? "";
  if (
    ["exact_verified", "approved_alias", "transformed_or_derived", "probable_review_required", "recoding_evidence_required"].includes(decision.mappingState) &&
    !candidate
  ) return "Select a bounded candidate code.";
  if (TERMINAL_STATES.has(decision.mappingState) && !rationale) return "Record an analyst rationale.";
  if (
    decision.mappingState === "ambiguous_review_required" &&
    new Set([candidate, ...(decision.alternativeAttributeCodes ?? [])].filter(Boolean)).size < 2
  ) return "Retain at least two bounded alternatives.";
  if (decision.mappingState === "approved_alias") {
    if (!decision.aliasAuthorityId?.trim() || !decision.institutionalAliasReference?.trim()) {
      return "Pin the alias authority and exact alias evidence reference.";
    }
  }
  if (decision.mappingState === "transformed_or_derived") {
    if (!(decision.sourceAttributeCodes?.length)) return "Identify at least one source attribute code.";
    if (!decision.transformationReferenceId?.trim() && !decision.transformationRule?.trim()) {
      return "Provide a transformation reference or rule.";
    }
    const operational = [
      decision.dataType,
      decision.units,
      decision.sourceSystem,
      decision.timing,
      decision.specialValueHandling,
      decision.valueRangeReconciliation,
      decision.specialValueReconciliation,
    ];
    if (operational.some((value) => !value?.trim())) return "Complete every operational reconciliation field.";
    if (!(decision.transformationOrRecodingConcerns?.length)) return "Record at least one transformation concern.";
  }
  if (decision.mappingState === "recoding_evidence_required" && !(decision.transformationOrRecodingConcerns?.length)) {
    return "Record the unresolved recoding concern.";
  }
  return null;
}

function StateBadge({ state }: { state: BureauCrosswalkState }) {
  return (
    <span className={`inline-flex rounded-full border px-2 py-1 text-[10px] font-bold uppercase tracking-wide ${STATE_TONES[state]}`}>
      {STATE_LABELS[state]}
    </span>
  );
}

function StateCountGrid({ counts }: { counts: BureauCrosswalkStateCounts }) {
  return (
    <div className="grid gap-2 sm:grid-cols-3 xl:grid-cols-5" data-testid="bureau-crosswalk-state-counts">
      {BUREAU_CROSSWALK_STATES.map((state) => (
        <div key={state} className={`rounded-lg border px-2.5 py-2 ${STATE_TONES[state]}`} data-state={state}>
          <div className="text-[9px] font-bold uppercase leading-4 tracking-wide">{STATE_LABELS[state]}</div>
          <div className="mt-1 text-sm font-semibold tabular-nums">{counts[state].toLocaleString()}</div>
        </div>
      ))}
    </div>
  );
}

function FieldEditor({
  draft,
  candidates,
  persistedDecision,
  selected,
  onSelected,
  onChange,
}: {
  draft: DecisionDraft;
  candidates: BureauCrosswalkCandidate[];
  persistedDecision?: BureauCrosswalkDecision;
  selected: boolean;
  onSelected: (selected: boolean) => void;
  onChange: (next: DecisionDraft) => void;
}) {
  const codes = Array.from(new Set([
    ...candidateCodes(candidates),
    ...(draft.candidateAttributeCode ? [draft.candidateAttributeCode] : []),
    ...(draft.alternativeAttributeCodes ?? []),
  ])).sort((left, right) => left.localeCompare(right));
  const issue = decisionIssue(draft);
  const update = (patch: Partial<DecisionDraft>) => {
    onSelected(true);
    onChange({ ...draft, ...patch });
  };
  const selectedCandidate = candidates.find((candidate) => candidate.candidateAttributeCode === draft.candidateAttributeCode);
  const stateChange = (mappingState: BureauCrosswalkState) => {
    const patch: Partial<DecisionDraft> = { mappingState };
    if (mappingState === "out_of_catalog") patch.candidateAttributeCode = undefined;
    if (mappingState !== "ambiguous_review_required") patch.alternativeAttributeCodes = [];
    if (mappingState !== "approved_alias") {
      patch.aliasAuthorityId = undefined;
      patch.institutionalAliasReference = undefined;
    } else if (selectedCandidate?.institutionalAliasReference) {
      patch.institutionalAliasReference = selectedCandidate.institutionalAliasReference;
    }
    update(patch);
  };

  return (
    <tr className="align-top" data-testid={`bureau-crosswalk-row-${draft.datasetField}`} data-mapping-state={draft.mappingState}>
      <td className="border-b border-slate-100 px-3 py-3">
        <input
          type="checkbox"
          checked={selected}
          onChange={(event) => onSelected(event.target.checked)}
          aria-label={`Include ${draft.datasetField} in this decision batch`}
        />
      </td>
      <td className="min-w-48 border-b border-slate-100 px-3 py-3">
        <div className="font-semibold text-slate-950">{draft.datasetField}</div>
        <div className="mt-1 text-[11px] leading-4 text-slate-500">
          {candidates.length ? `${candidates.length} bounded candidate${candidates.length === 1 ? "" : "s"}` : "No supported candidate"}
        </div>
      </td>
      <td className="min-w-56 border-b border-slate-100 px-3 py-3">
        <select
          className="w-full rounded-lg border border-slate-300 bg-white px-2 py-2 text-xs text-slate-950"
          value={draft.mappingState}
          onChange={(event) => stateChange(event.target.value as BureauCrosswalkState)}
          aria-label={`Governance state for ${draft.datasetField}`}
        >
          {BUREAU_CROSSWALK_STATES.map((state) => <option key={state} value={state}>{STATE_LABELS[state]}</option>)}
        </select>
        <div className="mt-2"><StateBadge state={draft.mappingState} /></div>
      </td>
      <td className="min-w-64 border-b border-slate-100 px-3 py-3">
        {draft.mappingState !== "out_of_catalog" ? (
          <select
            className="w-full rounded-lg border border-slate-300 bg-white px-2 py-2 text-xs text-slate-950"
            value={draft.candidateAttributeCode ?? ""}
            onChange={(event) => update({ candidateAttributeCode: event.target.value || undefined })}
            aria-label={`Candidate attribute for ${draft.datasetField}`}
          >
            <option value="">No candidate selected</option>
            {codes.map((code) => <option key={code} value={code}>{code}</option>)}
          </select>
        ) : <span className="text-xs text-slate-500">No catalog candidate by design</span>}
        <div className="mt-2 space-y-1 text-[11px] leading-4 text-slate-600">
          {candidates.slice(0, 4).map((candidate, index) => (
            <div key={`${candidate.candidateAttributeCode ?? "none"}-${candidate.matchStatus}-${index}`}>
              <span className="font-semibold">{candidate.candidateAttributeCode ?? "No code"}</span>
              {` · ATLAS heuristic: ${candidate.matchStatus} · ${(candidate.confidence * 100).toFixed(0)}% candidate confidence`}
            </div>
          ))}
          {persistedDecision?.evidence.length ? (
            <div className="mt-2 rounded border border-slate-200 bg-slate-50 px-2 py-1.5" data-testid={`bureau-crosswalk-evidence-${draft.datasetField}`}>
              <span className="font-semibold">Governed evidence references:</span>{" "}
              {Array.from(new Set(persistedDecision.evidence.map((item) => item.evidenceKind))).join(", ")} ({persistedDecision.evidence.length})
            </div>
          ) : null}
        </div>
      </td>
      <td className="min-w-80 border-b border-slate-100 px-3 py-3">
        <textarea
          className="min-h-16 w-full resize-y rounded-lg border border-slate-300 bg-white px-2 py-2 text-xs leading-4 text-slate-950"
          value={draft.rationale ?? ""}
          maxLength={2_048}
          onChange={(event) => update({ rationale: event.target.value })}
          placeholder={TERMINAL_STATES.has(draft.mappingState) ? "Required analyst rationale" : "Optional review note"}
          aria-label={`Rationale for ${draft.datasetField}`}
        />
        {draft.mappingState === "ambiguous_review_required" ? (
          <label className="mt-2 block text-[11px] font-semibold text-slate-700">
            Bounded alternatives (comma separated)
            <input
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 font-normal"
              value={(draft.alternativeAttributeCodes ?? []).join(", ")}
              onChange={(event) => update({ alternativeAttributeCodes: csvList(event.target.value) })}
            />
          </label>
        ) : null}
        {draft.mappingState === "approved_alias" ? (
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            <input className="rounded border border-slate-300 px-2 py-1.5 text-[11px]" value={draft.aliasAuthorityId ?? ""} onChange={(event) => update({ aliasAuthorityId: event.target.value })} placeholder="Alias authority ID" />
            <input className="rounded border border-slate-300 px-2 py-1.5 text-[11px]" value={draft.institutionalAliasReference ?? ""} onChange={(event) => update({ institutionalAliasReference: event.target.value })} placeholder="Exact alias evidence reference" />
          </div>
        ) : null}
        {draft.mappingState === "recoding_evidence_required" ? (
          <label className="mt-2 block text-[11px] font-semibold text-slate-700">
            Recoding concerns
            <input className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 font-normal" value={(draft.transformationOrRecodingConcerns ?? []).join(", ")} onChange={(event) => update({ transformationOrRecodingConcerns: csvList(event.target.value).slice(0, 16) })} />
          </label>
        ) : null}
        {draft.mappingState === "transformed_or_derived" ? (
          <div className="mt-2 grid gap-2 sm:grid-cols-2" data-testid={`bureau-crosswalk-transformation-${draft.datasetField}`}>
            <input className="rounded border border-slate-300 px-2 py-1.5 text-[11px]" value={(draft.sourceAttributeCodes ?? []).join(", ")} onChange={(event) => update({ sourceAttributeCodes: csvList(event.target.value) })} placeholder="Source attribute codes" />
            <input className="rounded border border-slate-300 px-2 py-1.5 text-[11px]" value={draft.transformationReferenceId ?? ""} onChange={(event) => update({ transformationReferenceId: event.target.value })} placeholder="Transformation reference ID" />
            <input className="rounded border border-slate-300 px-2 py-1.5 text-[11px] sm:col-span-2" value={draft.transformationRule ?? ""} onChange={(event) => update({ transformationRule: event.target.value })} placeholder="Transformation rule" />
            <input className="rounded border border-slate-300 px-2 py-1.5 text-[11px]" value={draft.dataType ?? ""} onChange={(event) => update({ dataType: event.target.value })} placeholder="Data type" />
            <input className="rounded border border-slate-300 px-2 py-1.5 text-[11px]" value={draft.units ?? ""} onChange={(event) => update({ units: event.target.value })} placeholder="Units" />
            <input className="rounded border border-slate-300 px-2 py-1.5 text-[11px]" value={draft.sourceSystem ?? ""} onChange={(event) => update({ sourceSystem: event.target.value })} placeholder="Source system" />
            <input className="rounded border border-slate-300 px-2 py-1.5 text-[11px]" value={draft.timing ?? ""} onChange={(event) => update({ timing: event.target.value })} placeholder="Timing" />
            <input className="rounded border border-slate-300 px-2 py-1.5 text-[11px]" value={draft.specialValueHandling ?? ""} onChange={(event) => update({ specialValueHandling: event.target.value })} placeholder="Special-value handling" />
            <input className="rounded border border-slate-300 px-2 py-1.5 text-[11px]" value={draft.valueRangeReconciliation ?? ""} onChange={(event) => update({ valueRangeReconciliation: event.target.value })} placeholder="Value-range reconciliation" />
            <input className="rounded border border-slate-300 px-2 py-1.5 text-[11px]" value={draft.specialValueReconciliation ?? ""} onChange={(event) => update({ specialValueReconciliation: event.target.value })} placeholder="Special-value reconciliation" />
            <input className="rounded border border-slate-300 px-2 py-1.5 text-[11px]" value={(draft.transformationOrRecodingConcerns ?? []).join(", ")} onChange={(event) => update({ transformationOrRecodingConcerns: csvList(event.target.value).slice(0, 16) })} placeholder="Transformation concerns" />
          </div>
        ) : null}
        {issue ? <div className="mt-2 text-[11px] font-semibold text-rose-700">{issue}</div> : null}
      </td>
    </tr>
  );
}

export default function BureauMetadataCrosswalkWorkspace({
  projectId,
  datasetIdentity,
  bindingRevision,
  bindingCurrent,
  onBindingRevisionChanged,
}: BureauMetadataCrosswalkWorkspaceProps) {
  const identityKey = `${projectId}:${datasetIdentity.dataset_id}:${datasetIdentity.dataset_version_id}:${datasetIdentity.activation_revision ?? "current"}`;
  const [action, setAction] = useState<ActionState>(null);
  const [error, setError] = useState<BureauMetadataRequestError | null>(null);
  const [governance, setGovernance] = useState<BureauCrosswalkGovernance | null>(null);
  const [preview, setPreview] = useState<BureauCrosswalkPreview | null>(null);
  const [drafts, setDrafts] = useState<DecisionDraft[]>([]);
  const [selectedFields, setSelectedFields] = useState<Set<string>>(new Set());
  const [analystReason, setAnalystReason] = useState("");
  const [currentBindingRevision, setCurrentBindingRevision] = useState(bindingRevision);
  const [partialRevision, setPartialRevision] = useState<number | null>(null);
  const [partialMessage, setPartialMessage] = useState("");
  const [history, setHistory] = useState<BureauCrosswalkHistory | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);

  useEffect(() => setCurrentBindingRevision(bindingRevision), [bindingRevision]);

  useEffect(() => {
    const controller = new AbortController();
    setAction("load");
    setError(null);
    setPreview(null);
    setGovernance(null);
    setDrafts([]);
    setSelectedFields(new Set());
    setPartialRevision(null);
    void getCurrentBureauMetadataCrosswalk({ projectId, datasetIdentity, signal: controller.signal })
      .then((current) => {
        if (controller.signal.aborted) return;
        setGovernance(current);
        setDrafts((current?.decisions ?? []).map(draftFromDecision));
        setDetailsOpen(current?.lifecycleState !== "confirmed");
      })
      .catch((caught) => {
        if (!controller.signal.aborted) setError(safeError(caught));
      })
      .finally(() => {
        if (!controller.signal.aborted) setAction(null);
      });
    return () => controller.abort();
  }, [identityKey, projectId]);

  const candidatesByField = useMemo(() => {
    const grouped = new Map<string, BureauCrosswalkCandidate[]>();
    for (const candidate of preview?.candidates ?? []) {
      const existing = grouped.get(candidate.datasetField) ?? [];
      existing.push(candidate);
      grouped.set(candidate.datasetField, existing);
    }
    return grouped;
  }, [preview]);
  const persistedDecisionByField = useMemo(
    () => new Map((governance?.decisions ?? []).map((decision) => [decision.datasetField, decision])),
    [governance],
  );
  const stateCounts = useMemo(() => countDraftStates(drafts), [drafts]);
  const selectedDrafts = drafts.filter((draft) => selectedFields.has(draft.datasetField));
  const selectedIssues = selectedDrafts.map(decisionIssue).filter(Boolean);
  const allConfirmable = drafts.length > 0 && drafts.every((draft) => TERMINAL_STATES.has(draft.mappingState) && !decisionIssue(draft));
  const reasonReady = analystReason.trim().length >= 8;
  const busy = action !== null;

  async function loadPreview() {
    if (busy || !bindingCurrent) return;
    setAction("preview");
    setError(null);
    try {
      const next = await previewBureauMetadataCrosswalk({ projectId, datasetIdentity });
      setPreview(next);
      if (!governance) setDrafts(next.decisions.map(draftFromDecision));
      setDetailsOpen(true);
    } catch (caught) {
      setError(safeError(caught));
    } finally {
      setAction(null);
    }
  }

  function updateDraft(field: string, next: DecisionDraft) {
    setDrafts((current) => current.map((draft) => draft.datasetField === field ? next : draft));
  }

  async function persist(confirmCrosswalk: boolean) {
    if (busy || !reasonReady) return;
    const decisions = confirmCrosswalk ? drafts : selectedDrafts;
    if (!decisions.length || decisions.some(decisionIssue)) return;
    setAction(confirmCrosswalk ? "confirm" : "save");
    setError(null);
    setPartialRevision(null);
    try {
      const result = await saveBureauMetadataCrosswalkDecisions({
        projectId,
        datasetIdentity,
        expectedCrosswalkRevision: governance?.revision ?? 0,
        expectedBindingRevision: currentBindingRevision,
        decisions,
        analystReason,
        confirmCrosswalk,
      });
      if (result.partialMetadataState) {
        setPartialRevision(result.crosswalkRevision ?? null);
        setPartialMessage(result.errorMessage ?? "The decision revision was saved, but its exact binding link requires retry.");
        return;
      }
      if (result.governance) {
        setGovernance(result.governance);
        setDrafts(result.governance.decisions.map(draftFromDecision));
        if (result.governance.bindingRevision) setCurrentBindingRevision(result.governance.bindingRevision);
        setSelectedFields(new Set());
        setAnalystReason("");
        setPreview(null);
        setDetailsOpen(result.governance.lifecycleState !== "confirmed");
        if (result.governance.bindingRevision) {
          onBindingRevisionChanged?.({
            bindingRevision: result.governance.bindingRevision,
            crosswalkId: result.governance.governanceId,
            crosswalkRevision: result.governance.revision,
          });
        }
      }
    } catch (caught) {
      setError(safeError(caught));
    } finally {
      setAction(null);
    }
  }

  async function retryBindingLink() {
    if (!partialRevision || busy || !reasonReady) return;
    setAction("retry");
    setError(null);
    try {
      const linked = await retryBureauMetadataCrosswalkBinding({
        projectId,
        datasetIdentity,
        crosswalkRevision: partialRevision,
        expectedBindingRevision: currentBindingRevision,
        analystReason,
      });
      setGovernance(linked);
      setDrafts(linked.decisions.map(draftFromDecision));
      if (linked.bindingRevision) setCurrentBindingRevision(linked.bindingRevision);
      setPartialRevision(null);
      setPartialMessage("");
      setSelectedFields(new Set());
      setAnalystReason("");
      if (linked.bindingRevision) {
        onBindingRevisionChanged?.({
          bindingRevision: linked.bindingRevision,
          crosswalkId: linked.governanceId,
          crosswalkRevision: linked.revision,
        });
      }
    } catch (caught) {
      setError(safeError(caught));
    } finally {
      setAction(null);
    }
  }

  async function loadHistory() {
    if (busy) return;
    setAction("history");
    setError(null);
    try {
      setHistory(await getBureauMetadataCrosswalkHistory({ projectId, datasetIdentity, limit: 25 }));
    } catch (caught) {
      setError(safeError(caught));
    } finally {
      setAction(null);
    }
  }

  if (!bindingCurrent) {
    return (
      <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-3 text-xs leading-5 text-amber-950" data-testid="bureau-crosswalk-binding-required">
        A current exact catalog binding is required before bounded crosswalk review. No mapping or modeling authority was changed.
      </div>
    );
  }

  return (
    <section className="mt-5 border-t border-blue-100 pt-5" data-testid="bureau-crosswalk-workspace" data-lifecycle={governance?.lifecycleState ?? "not_started"}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-wide text-blue-700">Project field governance · bounded review</div>
          <h3 className="mt-1 text-sm font-semibold text-slate-950">Dataset-to-Catalog Crosswalk</h3>
          <p className="mt-1 max-w-3xl text-xs leading-5 text-slate-600">
            Review server-generated candidates for this exact project, dataset, and version. Candidates are non-authoritative until an analyst records evidence and confirms a terminal decision. Generic field names remain unresolved unless evidence supports an explicit decision.
          </p>
        </div>
        <div className="flex flex-wrap gap-2 text-[10px] font-bold uppercase tracking-wide">
          <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-1">Binding r{currentBindingRevision}</span>
          <span className="rounded-full border border-blue-200 bg-blue-50 px-2 py-1 text-blue-800">Crosswalk {governance ? `r${governance.revision}` : "not started"}</span>
          {governance ? <span className={`rounded-full border px-2 py-1 ${governance.lifecycleState === "confirmed" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-amber-200 bg-amber-50 text-amber-800"}`}>{governance.lifecycleState.replaceAll("_", " ")}</span> : null}
        </div>
      </div>

      <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[11px] leading-5 text-slate-700" data-testid="bureau-crosswalk-nonmutation-notice">
        Crosswalk review creates bounded governance metadata only. It does not change the dataset, target contract, treatment, predictor authorization, Analysis Partition, feature manifest, or workflow route.
      </div>

      {action === "load" ? (
        <div className="mt-3 flex items-center gap-2 text-xs text-slate-600"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading the exact bounded crosswalk…</div>
      ) : null}
      {error ? (
        <div className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3" data-testid="bureau-crosswalk-error">
          <div className="flex items-start gap-2 text-xs font-semibold text-amber-950"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />{error.message}</div>
          <p className="mt-1 text-[11px] leading-5 text-amber-900">{error.recovery}</p>
        </div>
      ) : null}
      {partialRevision ? (
        <div className="mt-3 rounded-lg border border-orange-300 bg-orange-50 p-3" data-testid="bureau-crosswalk-partial-state">
          <div className="text-xs font-semibold text-orange-950">Decision revision {partialRevision} was persisted; the exact binding link is incomplete.</div>
          <p className="mt-1 text-[11px] leading-5 text-orange-900">{partialMessage} ATLAS will not present this revision as fully linked until retry succeeds.</p>
          <button type="button" className="mt-2 inline-flex items-center gap-2 rounded-lg bg-orange-700 px-3 py-2 text-xs font-semibold text-white disabled:bg-slate-300" disabled={!reasonReady || busy} onClick={() => void retryBindingLink()} data-testid="bureau-crosswalk-retry-link">
            {action === "retry" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Link2 className="h-3.5 w-3.5" />} Retry exact binding link
          </button>
        </div>
      ) : null}

      {governance?.lifecycleState === "confirmed" && !detailsOpen ? (
        <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-4" data-testid="bureau-crosswalk-confirmed-compact">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 h-4 w-4 text-emerald-700" />
              <div><div className="text-sm font-semibold text-emerald-950">Exact governed crosswalk confirmed</div><div className="mt-1 text-xs text-emerald-800">Revision {governance.revision} · {governance.decisions.length} bounded field decisions · checksum verified by the backend</div></div>
            </div>
            <button type="button" className="rounded-lg border border-emerald-300 bg-white px-3 py-2 text-xs font-semibold text-emerald-900" onClick={() => setDetailsOpen(true)}>Review decisions</button>
          </div>
        </div>
      ) : null}

      {(!governance || detailsOpen) ? (
        <>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <div className="text-xs text-slate-600">
              {preview ? `${preview.authorizedPredictorCount} authorized fields · ${preview.candidateCount} bounded candidates` : governance ? `${governance.decisions.length} governed field decisions` : "No persisted crosswalk decision revision"}
            </div>
            <div className="flex flex-wrap gap-2">
              <button type="button" className="inline-flex items-center gap-2 rounded-lg border border-blue-300 bg-white px-3 py-2 text-xs font-semibold text-blue-800 disabled:border-slate-200 disabled:text-slate-400" disabled={busy} onClick={() => void loadPreview()} data-testid="bureau-crosswalk-preview-button">
                {action === "preview" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />} {preview ? "Refresh bounded candidates" : "Generate bounded candidate review"}
              </button>
              {governance ? <button type="button" className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700" disabled={busy} onClick={() => void loadHistory()}><FileClock className="h-3.5 w-3.5" /> View revision history</button> : null}
              {governance?.lifecycleState === "confirmed" ? <button type="button" className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700" onClick={() => setDetailsOpen(false)}>Collapse confirmed state</button> : null}
            </div>
          </div>

          {drafts.length ? <div className="mt-3"><StateCountGrid counts={stateCounts} /></div> : null}

          {drafts.length ? (
            <div className="mt-4 overflow-x-auto rounded-xl border border-slate-200" data-testid="bureau-crosswalk-decision-table">
              <table className="w-full border-collapse text-left text-xs">
                <thead className="bg-slate-50 text-[10px] font-bold uppercase tracking-wide text-slate-600">
                  <tr><th className="px-3 py-2">Use</th><th className="px-3 py-2">Dataset field</th><th className="px-3 py-2">Governance state</th><th className="px-3 py-2">Bounded candidate evidence</th><th className="px-3 py-2">Analyst rationale / evidence</th></tr>
                </thead>
                <tbody className="bg-white">
                  {drafts.map((draft) => (
                    <FieldEditor
                      key={draft.datasetField}
                      draft={draft}
                      candidates={candidatesByField.get(draft.datasetField) ?? []}
                      persistedDecision={persistedDecisionByField.get(draft.datasetField)}
                      selected={selectedFields.has(draft.datasetField)}
                      onSelected={(selected) => setSelectedFields((current) => {
                        const next = new Set(current);
                        if (selected) next.add(draft.datasetField); else next.delete(draft.datasetField);
                        return next;
                      })}
                      onChange={(next) => updateDraft(draft.datasetField, next)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}

          {drafts.length ? (
            <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
              <label className="block text-xs font-semibold text-slate-700">
                Analyst decision reason
                <textarea className="mt-1 min-h-16 w-full resize-y rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs leading-5 text-slate-950" value={analystReason} maxLength={1_024} onChange={(event) => setAnalystReason(event.target.value)} placeholder="Explain the evidence basis and intended governance action (required, 8–1,024 characters)." data-testid="bureau-crosswalk-analyst-reason" />
              </label>
              <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                <div className="text-[11px] leading-5 text-slate-600">
                  {selectedDrafts.length} selected · {selectedIssues.length ? `${selectedIssues.length} selected decision(s) require more evidence` : "selected decisions are structurally ready"}. Confirmation is available only when every field has an evidence-complete terminal state.
                </div>
                <div className="flex flex-wrap gap-2">
                  <button type="button" className="inline-flex items-center gap-2 rounded-lg border border-blue-300 bg-white px-3 py-2 text-xs font-semibold text-blue-800 disabled:border-slate-200 disabled:text-slate-400" disabled={busy || !reasonReady || !selectedDrafts.length || selectedIssues.length > 0} onClick={() => void persist(false)} data-testid="bureau-crosswalk-save-decisions">
                    {action === "save" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />} Save selected decisions
                  </button>
                  <button type="button" className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-xs font-semibold text-white disabled:bg-slate-300" disabled={busy || !reasonReady || !allConfirmable} onClick={() => void persist(true)} data-testid="bureau-crosswalk-confirm">
                    {action === "confirm" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ShieldCheck className="h-3.5 w-3.5" />} Confirm complete crosswalk
                  </button>
                </div>
              </div>
            </div>
          ) : null}
        </>
      ) : null}

      {history ? (
        <div className="mt-4 rounded-lg border border-slate-200 bg-white p-3" data-testid="bureau-crosswalk-history">
          <button type="button" className="flex w-full items-center justify-between text-left text-xs font-semibold text-slate-800" onClick={() => setHistory(null)}>
            <span>Bounded revision history · {history.returned} of {history.totalRevisions}</span><ChevronDown className="h-4 w-4" />
          </button>
          <div className="mt-2 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {history.revisions.map((revision) => <div key={revision.revision} className="rounded border border-slate-200 bg-slate-50 px-3 py-2 text-[11px]"><div className="font-semibold">Revision {revision.revision} · {revision.lifecycleState.replaceAll("_", " ")}</div><div className="mt-1 text-slate-600">{revision.decisions.length} decisions · bounded checksum reference retained</div></div>)}
          </div>
        </div>
      ) : governance ? (
        <button type="button" className="mt-3 inline-flex items-center gap-1 text-[11px] font-semibold text-slate-600 hover:text-slate-950" disabled={busy} onClick={() => void loadHistory()}>{action === "history" ? <Loader2 className="h-3 w-3 animate-spin" /> : <ChevronRight className="h-3 w-3" />} Load bounded revision history</button>
      ) : null}
    </section>
  );
}
