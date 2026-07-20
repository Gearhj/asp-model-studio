import { useMemo, useState, type FormEvent } from "react";
import { MessageSquareText, Save, ShieldCheck, X } from "lucide-react";
import { useLocation } from "react-router-dom";
import { saveDemoFeedbackToDatabase } from "../lib/serverPersistence";
import { useWorkflowStore } from "../state/useWorkflowStore";

const DEMO_MODE_KEY = "atlas-private-demo-mode";
const DEMO_FEEDBACK_KEY = "atlas-private-demo-feedback";

type TesterFeedback = {
  feedbackId: string;
  projectId?: string;
  workflowType?: string;
  stepId?: string;
  issueType: string;
  severity: string;
  expectedBehavior: string;
  actualBehavior: string;
  notes: string;
  route: string;
  createdAt: string;
};

export default function PrivateDemoBanner() {
  const location = useLocation();
  const projectId = useWorkflowStore((state) => state.projectId);
  const workflowType = useWorkflowStore((state) => state.workflowId);
  const stepId = useWorkflowStore((state) => state.currentStepId);
  const enabled = useMemo(() => {
    const queryEnabled = new URLSearchParams(location.search).get("demo") === "1";
    const environmentEnabled = String((import.meta.env as Record<string, string | boolean | undefined>).VITE_DEMO_MODE ?? "").toLowerCase() === "true";
    const storedEnabled = typeof window !== "undefined" && localStorage.getItem(DEMO_MODE_KEY) === "true";
    if (queryEnabled && typeof window !== "undefined") localStorage.setItem(DEMO_MODE_KEY, "true");
    return queryEnabled || environmentEnabled || storedEnabled;
  }, [location.search]);
  const [open, setOpen] = useState(false);
  const [issueType, setIssueType] = useState("Workflow usability");
  const [severity, setSeverity] = useState("medium");
  const [expectedBehavior, setExpectedBehavior] = useState("");
  const [actualBehavior, setActualBehavior] = useState("");
  const [notes, setNotes] = useState("");
  const [message, setMessage] = useState("");

  if (!enabled) return null;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!actualBehavior.trim() && !notes.trim()) {
      setMessage("Describe the actual behavior or add notes before saving feedback.");
      return;
    }
    const feedback: TesterFeedback = {
      feedbackId: crypto.randomUUID(),
      projectId: projectId || undefined,
      workflowType: workflowType || undefined,
      stepId: stepId || undefined,
      issueType,
      severity,
      expectedBehavior: expectedBehavior.trim(),
      actualBehavior: actualBehavior.trim(),
      notes: notes.trim(),
      route: `${location.pathname}${location.search}`,
      createdAt: new Date().toISOString(),
    };
    let existing: TesterFeedback[] = [];
    try {
      const parsed = JSON.parse(localStorage.getItem(DEMO_FEEDBACK_KEY) || "[]");
      existing = Array.isArray(parsed) ? parsed as TesterFeedback[] : [];
    } catch {
      existing = [];
    }
    try {
      await saveDemoFeedbackToDatabase(feedback as unknown as Record<string, unknown>);
      localStorage.setItem(DEMO_FEEDBACK_KEY, JSON.stringify([...existing, feedback]));
      setExpectedBehavior("");
      setActualBehavior("");
      setNotes("");
      setMessage("Feedback saved to the ATLAS tester feedback log.");
    } catch (error) {
      localStorage.setItem(DEMO_FEEDBACK_KEY, JSON.stringify([...existing, feedback]));
      setMessage(error instanceof Error ? `Backend save failed. Feedback remains in this browser. ${error.message}` : "Backend save failed. Feedback remains in this browser.");
    }
  }

  return (
    <>
      <div className="border-b border-amber-300 bg-amber-50 px-4 py-2 text-amber-950">
        <div className="mx-auto flex max-w-[1760px] flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm font-semibold">
            <ShieldCheck size={16} />
            Private ATLAS demo. Use synthetic or non-sensitive data only.
          </div>
          <button type="button" onClick={() => setOpen(true)} className="inline-flex items-center gap-2 text-sm font-semibold text-amber-950 hover:text-amber-700">
            <MessageSquareText size={15} /> Tester feedback
          </button>
        </div>
      </div>
      {open && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-950/45 p-4" role="dialog" aria-modal="true" aria-label="Private demo feedback">
          <form onSubmit={submit} className="w-full max-w-xl rounded-lg border border-slate-200 bg-white p-5 shadow-2xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold text-slate-950">Private Demo Feedback</h2>
                <p className="mt-1 text-sm leading-6 text-slate-600">Feedback is saved to the ATLAS tester log with the current route, project, workflow, and step context.</p>
              </div>
              <button type="button" onClick={() => setOpen(false)} className="rounded p-1 text-slate-500 hover:bg-slate-100" aria-label="Close feedback form"><X size={18} /></button>
            </div>
            <div className="mt-5 grid gap-4 sm:grid-cols-2">
              <label className="grid gap-1 text-xs font-semibold uppercase text-slate-500">Issue type
                <select value={issueType} onChange={(event) => setIssueType(event.target.value)} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal normal-case text-slate-950">
                  <option>Workflow usability</option><option>Analytics accuracy</option><option>Visual design</option><option>Evidence and governance</option><option>Performance</option><option>Defect</option>
                </select>
              </label>
              <label className="grid gap-1 text-xs font-semibold uppercase text-slate-500">Severity
                <select value={severity} onChange={(event) => setSeverity(event.target.value)} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal normal-case text-slate-950">
                  <option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="blocking">Blocking</option>
                </select>
              </label>
            </div>
            <label className="mt-4 grid gap-1 text-xs font-semibold uppercase text-slate-500">Expected behavior
              <textarea value={expectedBehavior} onChange={(event) => setExpectedBehavior(event.target.value)} rows={3} className="resize-y rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal normal-case leading-6 text-slate-950" placeholder="What should ATLAS have done?" />
            </label>
            <label className="mt-4 grid gap-1 text-xs font-semibold uppercase text-slate-500">Actual behavior
              <textarea value={actualBehavior} onChange={(event) => setActualBehavior(event.target.value)} rows={3} className="resize-y rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal normal-case leading-6 text-slate-950" placeholder="What happened instead?" />
            </label>
            <label className="mt-4 grid gap-1 text-xs font-semibold uppercase text-slate-500">Additional notes
              <textarea value={notes} onChange={(event) => setNotes(event.target.value)} rows={3} className="resize-y rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal normal-case leading-6 text-slate-950" placeholder="Add reproduction steps or other context." />
            </label>
            {message && <div className="mt-3 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-900">{message}</div>}
            <div className="mt-5 flex justify-end gap-2">
              <button type="button" onClick={() => setOpen(false)} className="atlas-secondary-button">Cancel</button>
              <button type="submit" className="atlas-primary-button inline-flex items-center gap-2"><Save size={15} /> Save Feedback</button>
            </div>
          </form>
        </div>
      )}
    </>
  );
}
