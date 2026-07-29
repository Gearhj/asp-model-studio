import { AlertTriangle, Copy, Play, Save } from "lucide-react";
import { useState } from "react";
import type { CodeLanguage, CodeRunResult, PythonDiagnostics } from "../../lib/codeExecution";
import type { CodeContextMismatchDetail } from "../../lib/codeContextSafety";
import { CodeExecutionResult } from "./CodeExecutionResult";
import { CodeLanguageTabs } from "./CodeLanguageTabs";

export type CodeWorkspaceContextSafety = {
  warning: string;
  details: CodeContextMismatchDetail[];
  acknowledged: boolean;
  statusMessage?: string;
  savingCopy?: boolean;
  onKeepHistorical?: () => void;
  onResetForCurrentContext?: () => void;
  onAcknowledge?: () => void;
  onSaveAsNotebookCopy?: () => void;
};

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
  canSave?: boolean;
  saveLabel?: string;
  contextSafety?: CodeWorkspaceContextSafety;
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
  const [diffByLanguage, setDiffByLanguage] = useState<Partial<Record<CodeLanguage, boolean>>>({});
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

      {current.contextSafety ? (
        <div className="mt-4 rounded-xl border-2 border-amber-400 bg-amber-50 p-4 text-amber-950" role="alert">
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 shrink-0" size={19} aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <p className="font-semibold">{current.contextSafety.warning}</p>
              <p className="mt-1 text-sm">
                The historical draft remains unchanged and is not treated as current workflow evidence unless you
                acknowledge this exact draft and current-context pair.
              </p>
              {current.contextSafety.details.length ? (
                <dl className="mt-3 grid gap-2 sm:grid-cols-2">
                  {current.contextSafety.details.map((detail) => (
                    <div key={detail.field} className="rounded-lg border border-amber-200 bg-white/80 px-3 py-2">
                      <dt className="text-xs font-semibold uppercase tracking-wide text-amber-800">{detail.label}</dt>
                      <dd className="mt-1 break-words text-xs text-slate-700">
                        Historical: {detail.draftValue}
                        <br />
                        Current: {detail.currentValue}
                      </dd>
                    </div>
                  ))}
                </dl>
              ) : null}
              {current.contextSafety.acknowledged ? (
                <p className="mt-3 rounded-lg bg-emerald-50 px-3 py-2 text-sm font-medium text-emerald-900">
                  Acknowledged for this exact draft/current-context pair. Editing the code invalidates the
                  acknowledgement.
                </p>
              ) : null}
              {current.contextSafety.statusMessage ? (
                <p className="mt-3 text-sm font-medium" role="status">
                  {current.contextSafety.statusMessage}
                </p>
              ) : null}
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={current.contextSafety.onKeepHistorical}
                  className="rounded-lg border border-amber-300 bg-white px-3 py-2 text-xs font-semibold text-amber-950"
                >
                  Keep historical draft
                </button>
                <button
                  type="button"
                  onClick={current.contextSafety.onResetForCurrentContext}
                  className="rounded-lg border border-amber-300 bg-white px-3 py-2 text-xs font-semibold text-amber-950"
                >
                  Reset to current generated code
                </button>
                <button
                  type="button"
                  onClick={() =>
                    setDiffByLanguage((value) => ({
                      ...value,
                      [current.language]: !value[current.language],
                    }))
                  }
                  className="rounded-lg border border-amber-300 bg-white px-3 py-2 text-xs font-semibold text-amber-950"
                >
                  {diffByLanguage[current.language] ? "Hide diff" : "View diff"}
                </button>
                <button
                  type="button"
                  onClick={current.contextSafety.onSaveAsNotebookCopy}
                  disabled={current.contextSafety.savingCopy}
                  className="rounded-lg border border-amber-300 bg-white px-3 py-2 text-xs font-semibold text-amber-950 disabled:opacity-60"
                >
                  {current.contextSafety.savingCopy
                    ? "Saving notebook version..."
                    : "Save as separate notebook version (copy)"}
                </button>
                {!current.contextSafety.acknowledged ? (
                  <button
                    type="button"
                    onClick={current.contextSafety.onAcknowledge}
                    className="rounded-lg bg-amber-900 px-3 py-2 text-xs font-semibold text-white"
                  >
                    Acknowledge exact context pair
                  </button>
                ) : null}
              </div>
            </div>
          </div>
          {diffByLanguage[current.language] ? (
            <div className="mt-4 rounded-lg border border-slate-300 bg-slate-950 p-3">
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-300">
                Generated vs. historical draft
              </div>
              <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-5 text-slate-100">
                {simpleLineDiff(current.generatedCode, current.userCode)}
              </pre>
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" onClick={current.onRun} disabled={!current.canRun || current.running} className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white disabled:bg-slate-400">
          <Play size={15} /> {current.running ? "Running..." : current.runLabel}
        </button>
        <button type="button" onClick={current.onCopy} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700">
          <Copy size={15} /> Copy Code
        </button>
        <button type="button" onClick={current.onSave} disabled={current.canSave === false} className="inline-flex items-center gap-2 rounded-lg border border-emerald-200 bg-white px-3 py-2 text-sm font-semibold text-emerald-800 disabled:border-slate-200 disabled:text-slate-400">
          <Save size={15} /> {current.saveLabel ?? `Save ${current.label} as Insight`}
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

function simpleLineDiff(generatedCode: string, historicalCode: string) {
  const generated = generatedCode.split(/\r?\n/);
  const historical = historicalCode.split(/\r?\n/);
  const output: string[] = [];
  const lineCount = Math.min(Math.max(generated.length, historical.length), 240);
  for (let index = 0; index < lineCount; index += 1) {
    const generatedLine = generated[index];
    const historicalLine = historical[index];
    if (generatedLine === historicalLine) {
      output.push(`  ${generatedLine ?? ""}`);
      continue;
    }
    if (generatedLine !== undefined) output.push(`- ${generatedLine}`);
    if (historicalLine !== undefined) output.push(`+ ${historicalLine}`);
  }
  if (Math.max(generated.length, historical.length) > lineCount) {
    output.push("… diff truncated after 240 aligned lines");
  }
  return output.join("\n");
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
