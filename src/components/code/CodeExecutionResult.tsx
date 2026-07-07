import type { CodeRunResult, PythonDiagnostics } from "../../lib/codeExecution";

export function CodeExecutionResult({ result, diagnostics, cleanStderr }: { result: CodeRunResult | null; diagnostics?: PythonDiagnostics | null; cleanStderr?: (value: string) => string }) {
  if (!result) return null;
  const ok = "ok" in result ? Boolean(result.ok) : result.status === "success";
  const partial = result.status === "partial";
  const neutral = result.status === "template" || result.status === "unavailable";
  const stderr = "stderr" in result ? (cleanStderr ? cleanStderr(result.stderr ?? "") : result.stderr ?? "") : "";
  const stdout = "stdout" in result ? result.stdout ?? "" : "";
  const log = "log" in result ? result.log ?? "" : "";
  const listing = "listing" in result ? result.listing ?? "" : "";
  const sasCompatible = "translatedPython" in result || ("tables" in result && Boolean(result.tables?.length));
  const panelClass = neutral
    ? "border-blue-200 bg-blue-50"
    : partial
      ? "border-amber-200 bg-amber-50"
    : ok
      ? "border-emerald-200 bg-emerald-50"
      : "border-rose-200 bg-rose-50";
  return (
    <div className={`mt-4 rounded-xl border p-4 text-sm ${panelClass}`}>
      <div className="flex flex-wrap items-center justify-between gap-2 font-semibold">
        <span>{neutral ? "Template validation guidance" : partial ? "SAS-compatible execution partially completed" : ok ? (sasCompatible ? "SAS-compatible execution succeeded" : stderr ? "Execution completed with warnings" : "Execution succeeded") : "Execution returned an issue"}</span>
        <span>{result.status ?? (ok ? "success" : "error")} - {"runtimeMs" in result ? result.runtimeMs : 0} ms - return code {"returnCode" in result ? result.returnCode ?? "-" : "-"}</span>
      </div>
      {"rows" in result && result.rows?.length ? <ResultTable columns={result.columns} rows={result.rows} /> : null}
      {"tables" in result && result.tables?.length ? (
        <div className="mt-4 space-y-4">
          {result.tables.map((table, index) => <ResultTable key={`${table.title}-${index}`} title={table.title} columns={table.columns} rows={table.rows} />)}
        </div>
      ) : null}
      {"unsupportedStatements" in result && result.unsupportedStatements?.length ? (
        <div className="mt-4 rounded-lg border border-amber-200 bg-white p-3 text-xs text-amber-900">
          <div className="font-semibold uppercase tracking-wide">Unsupported SAS statements</div>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            {result.unsupportedStatements.map((statement, index) => <li key={`${statement}-${index}`}>{statement}</li>)}
          </ul>
        </div>
      ) : null}
      <div className="mt-3 grid gap-3 xl:grid-cols-2">
        <OutputBlock title={listing ? "LISTING / STDOUT" : "STDOUT / RESULT"} text={listing || stdout || ("rows" in result ? `${result.rowCount} rows returned.` : "No stdout captured.")} />
        {(!ok || stderr || log) && <OutputBlock title={log ? "LOG / STDERR" : ok ? "WARNINGS" : "STDERR / ERRORS"} text={log || stderr || ("error" in result ? result.error ?? "No error detail returned." : "No stderr captured.")} />}
      </div>
      {"translatedPython" in result && result.translatedPython ? <div className="mt-3"><OutputBlock title="TRANSLATED PYTHON" text={result.translatedPython} /></div> : null}
      {!ok && diagnostics && <DiagnosticsPanel diagnostics={diagnostics} />}
    </div>
  );
}

function ResultTable({ title, columns, rows }: { title?: string; columns: string[]; rows: Array<Record<string, unknown>> }) {
  return (
    <div className="mt-4 overflow-auto rounded-lg border border-slate-200 bg-white">
      {title ? <div className="border-b border-slate-200 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-700">{title}</div> : null}
      <table className="min-w-full text-left text-xs">
        <thead className="sticky top-0 bg-slate-100 text-slate-600">
          <tr>{columns.map((column) => <th key={column} className="px-3 py-2 font-semibold uppercase tracking-wide">{column}</th>)}</tr>
        </thead>
        <tbody>
          {rows.slice(0, 50).map((row, index) => (
            <tr key={index} className={index % 2 ? "bg-slate-50" : "bg-white"}>
              {columns.map((column) => <td key={column} className="max-w-[220px] break-words px-3 py-2 text-slate-800">{String(row[column] ?? "")}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function OutputBlock({ title, text }: { title: string; text: string }) {
  return (
    <div>
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{title}</div>
      <pre className="mt-1 max-h-72 overflow-auto rounded-lg bg-slate-950 p-3 text-xs leading-5 text-slate-100">{text}</pre>
    </div>
  );
}

function DiagnosticsPanel({ diagnostics }: { diagnostics: PythonDiagnostics }) {
  const rows = [
    ["Python executable", diagnostics.pythonExecutable],
    ["Python version", diagnostics.pythonVersion.split("\n")[0]],
    ["Working directory", diagnostics.cwd],
    ["Temp execution directory", diagnostics.runtimeRoot],
    ["Temp directory exists", diagnostics.runtimeRootExists ? "Yes" : "No"],
    ["Can start Python", diagnostics.canStartPython ? "Yes" : "No"],
    ["Can import site", diagnostics.canImportSite ? "Yes" : "No"],
    ["Can import pandas", diagnostics.canImportPandas ? "Yes" : "No"],
    ["Can capture stdout", diagnostics.canCaptureStdout ? "Yes" : "No"],
    ["Can capture stderr", diagnostics.canCaptureStderr ? "Yes" : "No"],
  ];
  return (
    <div className="mt-4 rounded-lg border border-amber-200 bg-white p-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-amber-700">Local Python Diagnostics</div>
      <div className="mt-2 grid gap-2 md:grid-cols-2">
        {rows.map(([label, value]) => (
          <div key={label} className="rounded border border-slate-200 bg-slate-50 px-2 py-1">
            <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
            <div className="break-words text-xs font-semibold text-slate-900">{value}</div>
          </div>
        ))}
      </div>
      {diagnostics.environmentWarnings?.length ? <ul className="mt-2 list-disc pl-5 text-xs text-amber-900">{diagnostics.environmentWarnings.map((warning) => <li key={warning}>{warning}</li>)}</ul> : null}
    </div>
  );
}
