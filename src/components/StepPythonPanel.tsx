import { useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import { Code2, Play } from "lucide-react";
import { logDecision } from "../lib/decisionJournal";
import { getNotebookSections, USER_STEP_PYTHON_CODE_KEY, type NotebookSection } from "../lib/notebookExport";
import { useWorkflowStore } from "../state/useWorkflowStore";

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

type PythonRunResult = {
  ok: boolean;
  status?: "success" | "error" | "timeout" | "unavailable" | "empty";
  stdout: string;
  stderr: string;
  runtimeMs: number;
  returnCode?: number;
};

function readStepCode() {
  try {
    const parsed = JSON.parse(localStorage.getItem(USER_STEP_PYTHON_CODE_KEY) || "{}");
    return parsed && typeof parsed === "object" ? (parsed as Record<string, string>) : {};
  } catch {
    return {};
  }
}

function writeStepCode(next: Record<string, string>) {
  localStorage.setItem(USER_STEP_PYTHON_CODE_KEY, JSON.stringify(next));
  window.dispatchEvent(new CustomEvent("step-python-code-updated"));
}

function sectionsForRoute(route: string) {
  return getNotebookSections().filter((section) => section.routes.includes(route));
}

function combinedGeneratedCode(sections: NotebookSection[]) {
  return sections.map((section) => `# ${section.title}\n${section.code}`).join("\n\n");
}

function combinedUserCode(sections: NotebookSection[], codeByStep: Record<string, string>) {
  return sections.map((section) => codeByStep[section.sectionKey] ?? "").filter(Boolean).join("\n\n");
}

export default function StepPythonPanel() {
  const location = useLocation();
  const sections = useMemo(() => sectionsForRoute(location.pathname), [location.pathname]);
  const workflowState = useWorkflowStore();
  const [expanded, setExpanded] = useState(false);
  const [codeByStep, setCodeByStep] = useState<Record<string, string>>(() => readStepCode());
  const [draftCode, setDraftCode] = useState("");
  const [lastSaved, setLastSaved] = useState("");
  const [runResult, setRunResult] = useState<PythonRunResult | null>(null);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    const next = readStepCode();
    const combined = combinedUserCode(sections, next);
    setCodeByStep(next);
    setDraftCode(combined);
    setLastSaved(combined);
  }, [sections]);

  if (!sections.length) return null;

  const generatedCode = combinedGeneratedCode(sections);
  const pageTitle = sections.map((section) => section.title).join(" / ");
  const persistDraftIfNeeded = () => {
    if (draftCode === lastSaved) return codeByStep;
    const next = { ...codeByStep };
    next[sections[0].sectionKey] = draftCode;
    writeStepCode(next);
    setCodeByStep(next);
    logDecision({
      workflowStep: sections.map((section) => section.title).join(" / "),
      actionType: "custom_python_code_edited",
      subject: "Step-level Python code",
      previousValue: `${lastSaved.length} characters`,
      newValue: `${draftCode.length} characters`,
      systemRecommendation:
        "Keep custom Python reproducible and aligned with the governed workflow transformations, metrics, and documentation.",
      followStatus: "not_applicable",
    });
    setLastSaved(draftCode);
    return next;
  };
  const saveDraft = () => {
    persistDraftIfNeeded();
  };

  const runUserPython = async () => {
    persistDraftIfNeeded();
    setRunning(true);
    setRunResult(null);
    try {
      const response = await fetch(`${API_BASE}/python/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          page: pageTitle,
          userCode: draftCode,
          projectId: workflowState.projectId,
          workflowStep: workflowState.currentStepId,
        }),
      });
      if (!response.ok) throw new Error(`Python execution request failed (${response.status}).`);
      const result = (await response.json()) as PythonRunResult;
      setRunResult(result);
    } catch (error) {
      setRunResult({
        ok: false,
        status: "unavailable",
        stdout: "",
        stderr:
          "Python execution backend is unavailable. Code will still be included in notebook export.",
        runtimeMs: 0,
      });
    } finally {
      setRunning(false);
    }
  };

  return (
    <section className="rounded-lg border border-slate-200/80 bg-white/90 shadow-sm">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
        onClick={() => setExpanded((current) => !current)}
      >
        <span className="flex items-center gap-2">
          <Code2 size={17} className="text-slate-700" />
          <span>
            <span className="block text-sm font-semibold text-slate-950">Python Code View</span>
            <span className="block text-xs text-slate-500">
              Generated reproducibility code and optional user-edited code for this workflow step.
            </span>
          </span>
        </span>
        <span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-600">
          {expanded ? "Hide" : "Show"}
        </span>
      </button>

      {expanded && (
        <div className="border-t border-slate-200 p-4">
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={runUserPython}
              disabled={running}
              className="inline-flex items-center gap-2 rounded-md bg-slate-950 px-3 py-2 text-xs font-semibold text-white shadow-sm hover:bg-slate-800 disabled:cursor-wait disabled:bg-slate-400"
            >
              <Play size={14} />
              {running ? "Running..." : "Run User Python"}
            </button>
            <span className="text-xs font-medium text-amber-700">
              Local development only. This executes only the user-edited Python below.
            </span>
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Generated Python</div>
              <pre className="max-h-[420px] overflow-auto rounded-lg bg-slate-950 p-3 text-xs leading-5 text-slate-100">
                {generatedCode}
              </pre>
            </div>
            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">User-Edited Python</div>
              <textarea
                className="h-[420px] w-full resize-y rounded-lg border border-slate-300 bg-white p-3 font-mono text-xs leading-5 text-slate-900 shadow-sm outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
                value={draftCode}
                onChange={(event) => setDraftCode(event.target.value)}
                onBlur={saveDraft}
                placeholder="Add custom Python for this workflow step. It will be included in the notebook export."
                spellCheck={false}
              />
            </div>
          </div>

          <PythonOutputPanel result={runResult} running={running} />
        </div>
      )}
    </section>
  );
}

function PythonOutputPanel({
  result,
  running,
}: {
  result: PythonRunResult | null;
  running: boolean;
}) {
  const isError = Boolean(result && !result.ok);
  return (
    <div className={`mt-4 rounded-xl border p-4 ${isError ? "border-rose-200 bg-rose-50" : "border-slate-200 bg-slate-50"}`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">Execution Output</h3>
          <p className="mt-1 text-xs text-slate-500">
            {running
              ? "Running user Python..."
              : result
                ? `User Python ${result.ok ? "completed" : "returned an issue"}.`
                : "Run user Python to see stdout, stderr, status, and runtime."}
          </p>
        </div>
        {result && (
          <div className="flex flex-wrap gap-2 text-xs font-semibold">
            <span className={`rounded-full px-2.5 py-1 ${result.ok ? "bg-emerald-100 text-emerald-700" : "bg-rose-100 text-rose-700"}`}>
              {result.status ?? (result.ok ? "success" : "error")}
            </span>
            <span className="rounded-full bg-white px-2.5 py-1 text-slate-600 ring-1 ring-slate-200">
              {result.runtimeMs.toLocaleString()} ms
            </span>
            {typeof result.returnCode === "number" && (
              <span className="rounded-full bg-white px-2.5 py-1 text-slate-600 ring-1 ring-slate-200">
                code {result.returnCode}
              </span>
            )}
          </div>
        )}
      </div>
      {running && <div className="mt-3 h-2 overflow-hidden rounded-full bg-white"><div className="h-full w-1/2 animate-pulse rounded-full bg-indigo-500" /></div>}
      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <OutputBlock title="stdout" text={result?.stdout ?? ""} emptyText="No stdout captured." />
        <OutputBlock title="stderr / errors" text={result?.stderr ?? ""} emptyText="No stderr captured." error={isError && Boolean(result?.stderr)} />
      </div>
    </div>
  );
}

function OutputBlock({
  title,
  text,
  emptyText,
  error = false,
}: {
  title: string;
  text: string;
  emptyText: string;
  error?: boolean;
}) {
  return (
    <div>
      <div className={`mb-2 text-xs font-semibold uppercase tracking-wide ${error ? "text-rose-700" : "text-slate-500"}`}>{title}</div>
      <pre className={`min-h-[96px] max-h-[320px] overflow-auto whitespace-pre-wrap rounded-lg p-3 text-xs leading-5 ${error ? "bg-white text-rose-800 ring-1 ring-rose-200" : "bg-slate-950 text-slate-100"}`}>
        {text?.trim() ? text : emptyText}
      </pre>
    </div>
  );
}
