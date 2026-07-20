import { Copy, Play, Save } from "lucide-react";
import { useState } from "react";
import type { CodeLanguage, CodeRunResult, PythonDiagnostics } from "../../lib/codeExecution";
import { CodeExecutionResult } from "./CodeExecutionResult";
import { CodeLanguageTabs } from "./CodeLanguageTabs";

export type CodeWorkspaceLanguageConfig = {
  language: CodeLanguage;
  label: string;
  supportBadge: string;
  generatedCode: string;
  userCode: string;
  setUserCode: (value: string) => void;
  note: string;
  runLabel: string;
  canRun: boolean;
  running?: boolean;
  result?: CodeRunResult | null;
  diagnostics?: PythonDiagnostics | null;
  onRun?: () => void;
  onCopy?: () => void;
  onSave?: () => void;
};

export function CodeWorkspacePanel({
  languages,
  defaultLanguage = "python",
  activeLanguage,
  onActiveLanguageChange,
  cleanStderr,
}: {
  languages: CodeWorkspaceLanguageConfig[];
  defaultLanguage?: CodeLanguage;
  activeLanguage?: CodeLanguage;
  onActiveLanguageChange?: (language: CodeLanguage) => void;
  cleanStderr?: (value: string) => string;
}) {
  const [internalActive, setInternalActive] = useState<CodeLanguage>(defaultLanguage);
  const active = activeLanguage ?? internalActive;
  const setActive = (language: CodeLanguage) => {
    setInternalActive(language);
    onActiveLanguageChange?.(language);
  };
  const current = languages.find((item) => item.language === active) ?? languages[0];
  const badges = languages.reduce((record, item) => ({ ...record, [item.language]: item.supportBadge }), {} as Partial<Record<CodeLanguage, string>>);

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h3 className="text-base font-semibold text-slate-950">Multi-Language Code Workspace</h3>
          <p className="mt-1 text-sm text-slate-600">Generated and user-edited code stay aligned to the selected dataset, question, pivot, and join context.</p>
        </div>
        <CodeLanguageTabs active={active} onChange={setActive} badges={badges} languages={languages.map((item) => item.language)} />
      </div>

      <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
        <span className="font-semibold">{current.label}:</span> {current.note}
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" onClick={current.onRun} disabled={!current.canRun || current.running} className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white disabled:bg-slate-400">
          <Play size={15} /> {current.running ? "Running..." : current.runLabel}
        </button>
        <button type="button" onClick={current.onCopy} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700">
          <Copy size={15} /> Copy Code
        </button>
        <button type="button" onClick={current.onSave} className="inline-flex items-center gap-2 rounded-lg border border-emerald-200 bg-white px-3 py-2 text-sm font-semibold text-emerald-800">
          <Save size={15} /> Save {current.label} as Insight
        </button>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <CodeBox title={`Generated ${current.label}`} value={current.generatedCode} readOnly />
        <CodeBox title={`User-Edited ${current.label}`} value={current.userCode} onChange={current.setUserCode} />
      </div>
      <CodeExecutionResult result={current.result ?? null} diagnostics={current.diagnostics ?? null} cleanStderr={cleanStderr} />
    </div>
  );
}

function CodeBox({ title, value, readOnly, onChange }: { title: string; value: string; readOnly?: boolean; onChange?: (value: string) => void }) {
  return (
    <label className="grid gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
      {title}
      <textarea
        className={`min-h-[300px] rounded-xl border border-slate-300 p-3 font-mono text-xs leading-5 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100 ${readOnly ? "bg-slate-950 text-slate-100" : "bg-white text-slate-900"}`}
        readOnly={readOnly}
        value={value}
        onChange={(event) => onChange?.(event.target.value)}
      />
    </label>
  );
}
