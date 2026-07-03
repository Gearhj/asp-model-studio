import { useState } from "react";
import { Wand2 } from "lucide-react";

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
};

function cleanNotes(value: string) {
  return value.trim().replace(/\s+/g, " ");
}

function ensurePeriod(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return trimmed;
  return /[.!?]$/.test(trimmed) ? trimmed : `${trimmed}.`;
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

async function requestDraft(label: string, currentValue: string, context?: Record<string, unknown>) {
  const notes = cleanNotes(currentValue);
  try {
    const response = await fetch(`${API_BASE}/copilot/draft-language`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ field: label, current_value: notes, mode: "rewrite", context }),
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
}: Props) {
  const [isDrafting, setIsDrafting] = useState(false);
  const [note, setNote] = useState("");

  return (
    <label className="grid gap-1.5">
      <span className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</span>
        <button
          type="button"
          className="inline-flex items-center gap-1 rounded-lg border border-blue-200 bg-blue-50 px-2 py-1 text-xs font-semibold text-blue-800 hover:bg-blue-100"
          onClick={async () => {
            if (!cleanNotes(value)) {
              setNote("Type rough notes first; Atlas will clean them up into governed documentation language.");
              return;
            }
            try {
              setIsDrafting(true);
              const draft = await requestDraft(label, value, context);
              onChange(draft);
              setNote("Language cleaned up from your notes. Review before saving.");
            } finally {
              setIsDrafting(false);
            }
          }}
        >
          <Wand2 size={13} />
          {isDrafting ? "Cleaning..." : "Clean Up with Atlas LLM"}
        </button>
      </span>
      <textarea
        className={`w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 ${minHeightClass} resize-y`}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
      />
      {note && <span className="text-xs text-blue-700">{note}</span>}
    </label>
  );
}
