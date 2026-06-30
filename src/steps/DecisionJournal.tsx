import { useEffect, useMemo, useState } from "react";
import { Download, FileClock, Trash2 } from "lucide-react";
import BrandLogo from "../components/BrandLogo";
import {
  exportDecisionJournalCsv,
  exportDecisionJournalMarkdown,
  loadDecisionJournal,
  saveDecisionJournal,
  type DecisionFollowStatus,
  type DecisionJournalEntry,
} from "../lib/decisionJournal";

const followOptions: DecisionFollowStatus[] = ["followed", "overrode", "not_applicable", "unknown"];

function downloadText(filename: string, text: string, type = "text/markdown") {
  const blob = new Blob([text], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export default function DecisionJournal() {
  const [entries, setEntries] = useState<DecisionJournalEntry[]>(() => loadDecisionJournal());
  const [filter, setFilter] = useState("");

  useEffect(() => {
    const refresh = () => setEntries(loadDecisionJournal());
    window.addEventListener("decision-journal-updated", refresh);
    window.addEventListener("storage", refresh);
    return () => {
      window.removeEventListener("decision-journal-updated", refresh);
      window.removeEventListener("storage", refresh);
    };
  }, []);

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return entries;
    return entries.filter((entry) =>
      [
        entry.workflowStep,
        entry.actionType,
        entry.subject,
        entry.previousValue,
        entry.newValue,
        entry.systemRecommendation,
        entry.followStatus,
        entry.userReason,
      ]
        .join(" ")
        .toLowerCase()
        .includes(q)
    );
  }, [entries, filter]);

  const updateEntry = (id: string, patch: Partial<DecisionJournalEntry>) => {
    const next = entries.map((entry) => (entry.id === id ? { ...entry, ...patch } : entry));
    setEntries(next);
    saveDecisionJournal(next);
  };

  const clearJournal = () => {
    if (!window.confirm("Clear the full decision journal? This removes the local audit trail.")) return;
    setEntries([]);
    saveDecisionJournal([]);
  };

  return (
    <div className="w-full space-y-5">
      <div className="flex flex-col gap-3 pt-2 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <BrandLogo size="md" variant="light" showSubtitle className="mb-3" />
          <div className="flex items-center gap-2">
            <FileClock size={20} className="text-slate-800" />
            <h1 className="text-xl font-semibold text-slate-950">Decision Journal</h1>
          </div>
          <p className="mt-1 text-sm text-slate-600">
            Review the automatically captured audit trail, document rationale, and export evidence for model governance and validation.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            className="w-64 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder="Filter journal..."
          />
          <button
            type="button"
            className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
            onClick={() => downloadText("decision-journal-audit-trail.md", exportDecisionJournalMarkdown(entries))}
          >
            <Download size={15} />
            Export Markdown
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
            onClick={() => downloadText("decision-journal-audit-trail.csv", exportDecisionJournalCsv(entries), "text/csv")}
          >
            <Download size={15} />
            Export CSV
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-medium text-rose-800 shadow-sm hover:bg-rose-100"
            onClick={clearJournal}
          >
            <Trash2 size={15} />
            Clear
          </button>
        </div>
      </div>

      <section className="grid gap-4 md:grid-cols-4">
        <Stat label="Journal Entries" value={entries.length} />
        <Stat label="Overrides" value={entries.filter((entry) => entry.followStatus === "overrode").length} />
        <Stat label="Rationales Added" value={entries.filter((entry) => entry.userReason?.trim()).length} />
        <Stat label="Visible" value={filtered.length} />
      </section>

      <section className="rounded-lg border border-slate-200/80 bg-white/90 shadow-sm">
        <div className="border-b border-slate-200 px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-950">Audit Trail</h2>
          <p className="mt-1 text-xs text-slate-500">
            Each entry captures the recommendation context at the time of the decision. Add rationale where the user overrides guidance or makes a material judgment call.
          </p>
        </div>

        {filtered.length === 0 ? (
          <div className="p-5 text-sm text-slate-500">
            No decision entries found. Actions such as target selection, feature inclusion, imputation, balancing, model selection, champion review, and final model save will appear here automatically.
          </div>
        ) : (
          <div className="grid gap-3 p-4">
            {filtered.map((entry) => (
              <article key={entry.id} className="rounded-lg border border-slate-200 bg-slate-50/70 p-4">
                <div className="grid gap-3 xl:grid-cols-[220px_1fr_190px]">
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                      {new Date(entry.timestamp).toLocaleString()}
                    </div>
                    <div className="mt-2 text-sm font-semibold text-slate-950">{entry.workflowStep}</div>
                    <div className="mt-1 text-xs text-slate-500">{entry.actionType}</div>
                  </div>

                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-slate-950">{entry.subject}</div>
                    <div className="mt-2 grid gap-2 md:grid-cols-2">
                      <ValueBox label="Previous" value={entry.previousValue} />
                      <ValueBox label="New" value={entry.newValue} />
                    </div>
                    <div className="mt-3 rounded-lg border border-blue-100 bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-900">
                      <span className="font-semibold">System recommendation: </span>
                      {entry.systemRecommendation}
                    </div>
                    <label className="mt-3 grid gap-1">
                      <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">User rationale</span>
                      <textarea
                        className="min-h-[72px] rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm"
                        value={entry.userReason ?? ""}
                        onChange={(event) => updateEntry(entry.id, { userReason: event.target.value })}
                        placeholder="Document why this decision was made, especially if guidance was overridden."
                      />
                    </label>
                  </div>

                  <label className="grid content-start gap-1">
                    <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                      Followed recommendation?
                    </span>
                    <select
                      className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm"
                      value={entry.followStatus}
                      onChange={(event) => updateEntry(entry.id, { followStatus: event.target.value as DecisionFollowStatus })}
                    >
                      {followOptions.map((option) => (
                        <option key={option} value={option}>
                          {option.replace("_", " ")}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-slate-200/80 bg-white/90 p-4 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-slate-950">{value}</div>
    </div>
  );
}

function ValueBox({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 break-words text-xs font-medium text-slate-800">{value}</div>
    </div>
  );
}
