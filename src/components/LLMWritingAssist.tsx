import { useState } from "react";
import { Check, Wand2, X } from "lucide-react";

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

type Props = {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  context?: Record<string, unknown>;
  minHeightClass?: string;
  actions?: WritingAssistAction[];
  strictGrounding?: boolean;
  onAcceptDraft?: (draft: string, action: WritingAssistAction) => void;
};

export type WritingAssistAction =
  | "Draft from current project context"
  | "Improve clarity"
  | "Rewrite for business audience"
  | "Rewrite for data scientist"
  | "Rewrite for model validator"
  | "Shorten"
  | "Expand"
  | "Identify missing information";

const defaultActions: WritingAssistAction[] = ["Improve clarity"];

function cleanNotes(value: string) {
  return value.trim().replace(/\s+/g, " ");
}

function ensurePeriod(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return trimmed;
  return /[.!?]$/.test(trimmed) ? trimmed : `${trimmed}.`;
}

function shorten(value: string) {
  const sentences = value.match(/[^.!?]+[.!?]?/g)?.map((item) => item.trim()).filter(Boolean) ?? [];
  const concise = sentences.slice(0, 2).join(" ");
  return concise.length <= 320 ? concise : `${concise.slice(0, 317).trimEnd()}...`;
}

function missingInformationReview(label: string) {
  if (/business objective/i.test(label)) return "Clarify the decision or process, the outcome expected to improve, and how improvement will be recognized.";
  if (/intended model use/i.test(label)) return "Clarify who uses the output, the action that may follow, where human judgment applies, and any prohibited automated action.";
  if (/target definition/i.test(label)) return "Clarify the real-world outcome, when it becomes final, and which records do not receive a valid outcome.";
  if (/population definition/i.test(label)) return "Clarify the eligible unit, inclusion boundary, exclusions, and intended scoring population.";
  if (/observation window/i.test(label)) return "Clarify which information is available when the score is generated and the relevant lookback period.";
  if (/performance window/i.test(label)) return "Clarify when outcome measurement starts, how long it remains open, and when the outcome is considered final.";
  if (/use boundaries/i.test(label)) return "Clarify approved uses, prohibited uses, human review expectations, and override authority.";
  return "Clarify scope, decision use, assumptions, accountable owner, and any known limitations.";
}

function contextText(context: Record<string, unknown> | undefined, key: string) {
  const value = context?.[key];
  return typeof value === "string" ? cleanNotes(value) : "";
}

function draftFromAcceptedContext(label: string, context?: Record<string, unknown>) {
  const businessObjective = contextText(context, "businessObjective");
  const intendedModelUse = contextText(context, "intendedModelUse");
  const targetDefinition = contextText(context, "targetDefinition");
  const populationDefinition = contextText(context, "populationDefinition");
  const observationWindow = contextText(context, "observationWindow");
  const performanceWindow = contextText(context, "performanceWindow");

  if (/business objective/i.test(label)) {
    const statements = [
      targetDefinition ? `The model will predict ${targetDefinition.replace(/[.]$/, "")}.` : "",
      populationDefinition ? `The eligible population is ${populationDefinition.replace(/[.]$/, "")}.` : "",
      intendedModelUse ? `The output is intended to support ${intendedModelUse.replace(/[.]$/, "")}.` : "",
    ].filter(Boolean);
    return statements.join(" ");
  }
  if (/intended model use/i.test(label) && businessObjective) {
    return `Use the model output to support the accepted business objective: ${ensurePeriod(businessObjective)}`;
  }
  if (/target definition/i.test(label)) return ensurePeriod(targetDefinition);
  if (/population definition/i.test(label)) return ensurePeriod(populationDefinition);
  if (/observation window/i.test(label)) return ensurePeriod(observationWindow);
  if (/performance window/i.test(label)) return ensurePeriod(performanceWindow);
  return "";
}

function groundedRewrite(label: string, currentValue: string, action: WritingAssistAction, context?: Record<string, unknown>) {
  const notes = cleanNotes(currentValue);
  if (action === "Identify missing information") return missingInformationReview(label);
  if (action === "Draft from current project context") return draftFromAcceptedContext(label, context) || ensurePeriod(notes);
  if (!notes) return "";
  if (action === "Shorten") return shorten(ensurePeriod(notes));
  if (action === "Expand") return `${ensurePeriod(notes)} ${missingInformationReview(label)}`;
  if (action === "Rewrite for business audience") return ensurePeriod(shorten(notes));
  if (action === "Rewrite for data scientist") return `Modeling context: ${ensurePeriod(notes)}`;
  if (action === "Rewrite for model validator") return `Statement for validation review: ${ensurePeriod(notes)}`;
  return ensurePeriod(notes);
}

function fallbackRewrite(label: string, currentValue: string) {
  const notes = cleanNotes(currentValue);
  if (/business objective/i.test(label)) {
    return `The business objective is to ${ensurePeriod(notes)} The model should support this objective through measurable performance improvement, documented decision logic, and ongoing monitoring against approved success metrics.`;
  }
  if (/intended/i.test(label)) {
    return `The model will be used to ${ensurePeriod(notes)} Use of the model should be limited to the approved population, governed decision process, documented controls, and monitoring framework.`;
  }
  if (/target/i.test(label)) {
    return `The target variable is defined as ${ensurePeriod(notes)} The final target definition should specify the positive outcome, measurement window, exclusion rules, and treatment of records without a valid observed outcome.`;
  }
  if (/population/i.test(label)) {
    return `The modeling population includes ${ensurePeriod(notes)} Eligibility criteria, exclusions, observation-window requirements, and population counts should be documented for development, validation, and monitoring.`;
  }
  if (/implementation/i.test(label)) {
    return `The implementation plan is to ${ensurePeriod(notes)} Before production use, the project team should confirm approved model artifacts, reproducible preprocessing, owner sign-off, deployment controls, rollback criteria, and monitoring readiness.`;
  }
  if (/monitoring/i.test(label)) {
    return `The monitoring approach is to ${ensurePeriod(notes)} The monitoring plan should define the cadence, selected metrics, thresholds, escalation path, remediation ownership, and documentation requirements.`;
  }
  return `${ensurePeriod(notes)} The final documentation should describe the scope, assumptions, governance controls, and known limitations.`;
}

async function requestDraft(label: string, currentValue: string, action: WritingAssistAction, context?: Record<string, unknown>, strictGrounding = false) {
  const notes = cleanNotes(currentValue);
  if (strictGrounding) return groundedRewrite(label, notes, action, context);
  try {
    const response = await fetch(`${API_BASE}/copilot/draft-language`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ field: label, current_value: notes, mode: action, context, grounding_rule: "Use only supplied accepted project context. Do not invent facts." }),
    });
    if (!response.ok) throw new Error("Draft endpoint unavailable");
    const data = await response.json();
    if (typeof data?.draft === "string" && data.draft.trim()) return data.draft.trim();
  } catch {
    // Fall back to deterministic language until an LLM endpoint is connected.
  }
  return fallbackRewrite(label, notes);
}

export default function LLMWritingAssist({
  label,
  value,
  onChange,
  placeholder,
  context,
  minHeightClass = "min-h-[104px]",
  actions = defaultActions,
  strictGrounding = false,
  onAcceptDraft,
}: Props) {
  const [isDrafting, setIsDrafting] = useState(false);
  const [note, setNote] = useState("");
  const [draft, setDraft] = useState("");
  const [action, setAction] = useState<WritingAssistAction>(actions[0] ?? "Improve clarity");
  const [draftAction, setDraftAction] = useState<WritingAssistAction>(actions[0] ?? "Improve clarity");
  const isReview = draftAction === "Identify missing information";

  return (
    <label className="grid gap-1.5">
      <span className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</span>
        <span className="flex flex-wrap items-center justify-end gap-2">
          {actions.length > 1 ? (
            <select className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs font-semibold text-slate-700" aria-label={`${label} ATLAS AI action`} value={action} onChange={(event) => setAction(event.target.value as WritingAssistAction)}>
              {actions.map((item) => <option key={item}>{item}</option>)}
            </select>
          ) : null}
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded-lg border border-blue-200 bg-blue-50 px-2 py-1 text-xs font-semibold text-blue-800 hover:bg-blue-100"
            onClick={async () => {
              const hasAcceptedContext = Object.values(context ?? {}).some((item) => typeof item === "string" && cleanNotes(item));
              if (!cleanNotes(value) && action !== "Identify missing information" && !(action === "Draft from current project context" && hasAcceptedContext)) {
                setNote("Add factual notes first so ATLAS can draft without inventing project details.");
                return;
              }
              try {
                setIsDrafting(true);
                const proposed = await requestDraft(label, value, action, context, strictGrounding);
                if (!proposed) {
                  setNote("ATLAS needs factual project context before it can propose language for this field.");
                  return;
                }
                setDraftAction(action);
                setDraft(proposed);
                setNote(action === "Identify missing information" ? "Review generated from the accepted project context. Your text is unchanged." : "Proposed language is ready for review. Your text is unchanged until you accept it.");
              } finally {
                setIsDrafting(false);
              }
            }}
          >
            <Wand2 size={13} />
            {isDrafting ? "Drafting..." : "Improve with ATLAS AI"}
          </button>
        </span>
      </span>
      <textarea
        className={`w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 ${minHeightClass} resize-y`}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
      />
      {draft ? (
        <div className="rounded-lg border border-blue-200 bg-blue-50 p-3">
          <div className="text-xs font-semibold uppercase tracking-wide text-blue-800">{isReview ? "ATLAS review" : "Proposed draft"}</div>
          <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-800">{draft}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {!isReview ? <button type="button" className="atlas-primary-button px-3 py-1.5 text-xs" onClick={() => { if (onAcceptDraft) onAcceptDraft(draft, draftAction); else onChange(draft); setDraft(""); setNote("Proposed draft accepted. Review and save when ready."); }}><Check size={13} /> Accept draft</button> : null}
            <button type="button" className="atlas-secondary-button px-3 py-1.5 text-xs" onClick={() => { setDraft(""); setNote("Proposal dismissed. Your original text is unchanged."); }}><X size={13} /> Dismiss</button>
          </div>
        </div>
      ) : null}
      {note && <span className="text-xs text-blue-700">{note}</span>}
    </label>
  );
}
