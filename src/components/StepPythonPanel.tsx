import { useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import { Code2 } from "lucide-react";
import { logDecision } from "../lib/decisionJournal";
import { getNotebookSections, USER_STEP_PYTHON_CODE_KEY, type NotebookSection } from "../lib/notebookExport";

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
  const [expanded, setExpanded] = useState(false);
  const [codeByStep, setCodeByStep] = useState<Record<string, string>>(() => readStepCode());
  const [draftCode, setDraftCode] = useState("");
  const [lastSaved, setLastSaved] = useState("");

  useEffect(() => {
    const next = readStepCode();
    const combined = combinedUserCode(sections, next);
    setCodeByStep(next);
    setDraftCode(combined);
    setLastSaved(combined);
  }, [sections]);

  if (!sections.length) return null;

  const generatedCode = combinedGeneratedCode(sections);
  const saveDraft = () => {
    if (draftCode === lastSaved) return;
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
        <div className="grid gap-4 border-t border-slate-200 p-4 xl:grid-cols-2">
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
      )}
    </section>
  );
}
