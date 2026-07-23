import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ChevronDown, FileUp, Save, ShieldCheck } from "lucide-react";
import {
  AtlasAttentionPanel,
  AtlasDataScopeBadge,
  AtlasWorkflowSection,
} from "./ui/AtlasWorkflow";
import {
  bureauMetadata,
  fetchBureauDetection,
  loadBureauReviewState,
  saveBureauReviewState,
  type BureauDeclaration,
  type BureauDetectionResponse,
  type BureauHandling,
  type BureauReviewDecision,
  type BureauReviewState,
} from "../lib/bureauDetection";
import { parseBureauMetadataCsv, saveBureauMetadata } from "../lib/creditBureau";
import { createEvidence } from "../lib/evidenceGraph";
import { logDecision } from "../lib/decisionJournal";
import { useWorkflowStore } from "../state/useWorkflowStore";

const handlingLabels: Record<BureauHandling, string> = {
  preserve_informative: "Preserve as informative special value",
  convert_to_missing: "Convert to missing",
  convert_to_category: "Convert to labeled category",
  documented_domain_mapping: "Replace using documented domain mapping",
  exclude_variable: "Exclude variable",
  leave_unchanged: "Leave unchanged",
  custom: "Custom treatment",
};

export default function BureauReviewPanel({ target, eventValue, enabled }: { target: string; eventValue: unknown; enabled: boolean }) {
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);
  const [state, setState] = useState<BureauReviewState>(loadBureauReviewState);
  const [result, setResult] = useState<BureauDetectionResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [metadataVersion, setMetadataVersion] = useState(0);

  async function runDetection(signal?: AbortSignal) {
    if (!enabled) return;
    setLoading(true);
    setError("");
    try {
      const payload = await fetchBureauDetection({ projectId, target, eventValue, state, metadata: bureauMetadata(), signal });
      setResult(payload);
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === "AbortError") return;
      setError(cause instanceof Error ? cause.message : "Credit bureau detection failed.");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void runDetection(controller.signal);
    return () => controller.abort();
    // Re-run only when the governed declaration, target, or metadata changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, target, eventValue, state.declaration, metadataVersion]);

  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("section") === "credit-bureau-review") {
      window.setTimeout(() => document.getElementById("credit-bureau-review")?.scrollIntoView({ behavior: "smooth", block: "start" }), 250);
    }
  }, []);

  const likelyVariables = useMemo(() => result?.variables.filter((row) => row.likely_bureau) ?? [], [result]);
  const shouldExpand = result?.detected || state.declaration === "contains" || state.declaration === "manual_review";

  function updateState(next: BureauReviewState) {
    setState(next);
    saveBureauReviewState(next);
  }

  function updateDecision(variable: string, value: number, patch: Partial<BureauReviewDecision>) {
    const existing = state.decisions.find((row) => row.variable === variable && row.value === value);
    const nextDecision: BureauReviewDecision = {
      variable,
      value,
      handling: patch.handling ?? existing?.handling ?? "preserve_informative",
      rationale: patch.rationale ?? existing?.rationale ?? "",
      updatedAt: new Date().toISOString(),
    };
    const next = {
      ...state,
      decisions: [nextDecision, ...state.decisions.filter((row) => !(row.variable === variable && row.value === value))],
    };
    updateState(next);
    logDecision({
      workflowStep: "Data Acquisition",
      actionType: "workflow_setting_changed",
      subject: `${variable} bureau special value ${value}`,
      previousValue: existing?.handling ?? "Not selected",
      newValue: nextDecision.handling,
      systemRecommendation: "Confirm a domain-supported special-value treatment and record reviewer rationale before applying it downstream.",
      userReason: nextDecision.rationale,
    });
  }

  async function uploadMetadata(file: File) {
    const rows = parseBureauMetadataCsv(await file.text());
    if (!rows.length) {
      setMessage("No valid bureau metadata rows were found in the selected CSV.");
      return;
    }
    saveBureauMetadata(rows);
    setMetadataVersion((value) => value + 1);
    setMessage(`${rows.length.toLocaleString()} bureau metadata rows loaded.`);
  }

  async function saveEvidence() {
    if (!result) return;
    setMessage("Saving bureau review evidence...");
    try {
      await createEvidence({
        projectId,
        projectName,
        evidenceType: "dataset",
        title: "Credit Bureau Detection and Special-Value Review",
        summary: result.detected
          ? `${result.likely_variable_count} likely bureau variables were reviewed using full-dataset evidence.`
          : "No credit bureau data was confirmed after automated and manual review.",
        sourcePage: "Data Acquisition",
        sourceRoute: "/step01?section=credit-bureau-review",
        datasetIds: [],
        modelIds: [],
        documentIds: [],
        notebookIds: [],
        supportsSections: ["Data Sources", "Data Quality", "Feature Engineering"],
        tags: ["predictive_modeling", "bureau_review", "special_values"],
        status: state.declaration === "manual_review" ? "needs_review" : "ready",
        importance: "high",
        lineage: { scope: result.scope, rowCount: result.row_count, target: result.target, metadataSource: result.metadata_source },
        payload: {
          detected: result.detected,
          confidence: result.confidence,
          reasons: result.reasons,
          variables: result.variables,
          declaration: state.declaration,
          decisions: state.decisions,
          reviewerRationale: state.rationale,
          reviewer: "Current ATLAS user",
          reviewedAt: result.reviewed_at,
        },
      });
      setMessage("Bureau review evidence saved.");
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : "Bureau review evidence could not be saved.");
    }
  }

  if (!enabled) return null;

  return (
    <section id="credit-bureau-review" className="scroll-mt-24">
      <details className="atlas-workflow-section atlas-workflow-section--info" open={!!shouldExpand}>
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3">
          <span className="flex min-w-0 items-center gap-3">
            <span className="rounded-lg bg-blue-100 p-2 text-blue-700"><ShieldCheck size={18} /></span>
            <span>
              <span className="block text-sm font-semibold text-slate-950">Credit Bureau Review</span>
              <span className="mt-0.5 block text-xs text-slate-600">
                {loading ? "Analyzing full-data signals" : result?.detected ? `${result.likely_variable_count} likely bureau variables detected` : "No bureau data confirmed; manual declaration remains available"}
              </span>
            </span>
          </span>
          <span className="flex items-center gap-2">
            {result ? <AtlasDataScopeBadge scope="full_dataset" rows={result.row_count} /> : null}
            <ChevronDown size={17} />
          </span>
        </summary>

        <div className="mt-4 space-y-4 border-t border-blue-200 pt-4">
          <div className="grid gap-3 lg:grid-cols-[minmax(240px,340px)_1fr_auto] lg:items-end">
            <label>
              <span className="atlas-label">Manual declaration</span>
              <select className="atlas-input mt-1" value={state.declaration} onChange={(event) => updateState({ ...state, declaration: event.target.value as BureauDeclaration })}>
                <option value="auto">Use multi-signal detection</option>
                <option value="contains">Contains credit bureau variables</option>
                <option value="does_not_contain">Does not contain credit bureau variables</option>
                <option value="manual_review">Requires manual review</option>
              </select>
            </label>
            <label>
              <span className="atlas-label">Reviewer rationale</span>
              <input className="atlas-input mt-1" value={state.rationale} onChange={(event) => updateState({ ...state, rationale: event.target.value })} placeholder="Document the source, override, or review basis." />
            </label>
            <label className="atlas-secondary-button cursor-pointer">
              <FileUp size={15} /> Upload metadata CSV
              <input className="hidden" type="file" accept=".csv,text/csv" onChange={(event) => event.target.files?.[0] && void uploadMetadata(event.target.files[0])} />
            </label>
          </div>

          {error ? <AtlasAttentionPanel title="Bureau detection unavailable" tone="danger">{error}</AtlasAttentionPanel> : null}

          {result ? (
            <>
              <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
                <Metric label="Detection" value={result.detected ? "Detected" : "Not detected"} tone={result.detected ? "warning" : "neutral"} />
                <Metric label="Confidence" value={`${Math.round(result.confidence * 100)}%`} />
                <Metric label="Likely variables" value={result.likely_variable_count.toLocaleString()} />
                <Metric label="With special values" value={result.variables_with_special_values.toLocaleString()} />
              </div>
              {result.reasons.length ? (
                <div className="rounded-lg border border-slate-200 bg-white p-3">
                  <div className="text-xs font-semibold uppercase text-slate-500">Detection reasons</div>
                  <ul className="mt-2 space-y-1 text-sm text-slate-700">{result.reasons.map((reason) => <li key={reason}>• {reason}</li>)}</ul>
                </div>
              ) : null}
              {result.detected && likelyVariables.length ? (
                <AtlasWorkflowSection title="Special-Value Treatment Review" description="Recommendations are advisory. A reviewer must confirm treatment and rationale before downstream application." tone="warning">
                  <div className="space-y-3">
                    {likelyVariables.map((variable) => (
                      <details key={variable.variable} className="rounded-lg border border-slate-200 bg-white" open={likelyVariables.length <= 3}>
                        <summary className="cursor-pointer px-3 py-2.5 text-sm font-semibold text-slate-950">
                          {variable.variable} <span className="ml-2 text-xs font-normal text-slate-500">{Math.round(variable.confidence * 100)}% confidence | {variable.special_value_count.toLocaleString()} special rows</span>
                        </summary>
                        <div className="overflow-auto border-t border-slate-200">
                          <table className="atlas-table min-w-[980px]">
                            <thead><tr><th>Value</th><th>Definition</th><th>Count</th><th>Frequency</th><th>Special event rate</th><th>Regular event rate</th><th>Selected handling</th><th>Rationale</th></tr></thead>
                            <tbody>
                              {variable.special_values.map((profile) => {
                                const decision = state.decisions.find((row) => row.variable === variable.variable && row.value === profile.value);
                                return (
                                  <tr key={`${variable.variable}-${profile.value}`}>
                                    <td className="font-semibold">{profile.value}</td>
                                    <td>{profile.definition}</td>
                                    <td>{profile.count.toLocaleString()}</td>
                                    <td>{(profile.frequency * 100).toFixed(2)}%</td>
                                    <td>{profile.event_rate === null ? "Not available" : `${(profile.event_rate * 100).toFixed(2)}%`}</td>
                                    <td>{profile.regular_event_rate === null ? "Not available" : `${(profile.regular_event_rate * 100).toFixed(2)}%`}</td>
                                    <td><select className="atlas-input min-w-56" value={decision?.handling ?? "preserve_informative"} onChange={(event) => updateDecision(variable.variable, profile.value, { handling: event.target.value as BureauHandling })}>{Object.entries(handlingLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></td>
                                    <td><input className="atlas-input min-w-64" value={decision?.rationale ?? ""} onChange={(event) => updateDecision(variable.variable, profile.value, { rationale: event.target.value })} placeholder="Required for override or custom treatment" /></td>
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        </div>
                      </details>
                    ))}
                  </div>
                </AtlasWorkflowSection>
              ) : null}
              {!result.detected && state.declaration === "auto" ? (
                <div className="rounded-lg border border-slate-200 bg-white p-3 text-sm text-slate-600">No variable met the multi-signal bureau threshold. A generic field containing a special-looking value is not classified as bureau data without supporting name, metadata, concentration, or reviewer evidence.</div>
              ) : null}
            </>
          ) : null}

          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className="atlas-primary-button" onClick={() => void saveEvidence()} disabled={!result}><Save size={15} /> Save bureau review evidence</button>
            {message ? <span className="text-sm text-slate-600">{message}</span> : null}
          </div>
        </div>
      </details>
    </section>
  );
}

function Metric({ label, value, tone = "neutral" }: { label: string; value: string; tone?: "neutral" | "warning" }) {
  return <div className={`rounded-lg border px-3 py-2 ${tone === "warning" ? "border-amber-300 bg-amber-50" : "border-slate-200 bg-white"}`}><div className="text-[10px] font-semibold uppercase text-slate-500">{label}</div><div className="mt-1 text-sm font-semibold text-slate-950">{value}</div></div>;
}
