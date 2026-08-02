import { useMemo, useState } from "react";
import { Download, NotebookTabs, RefreshCw } from "lucide-react";
import BrandLogo from "../components/BrandLogo";
import { buildWorkflowNotebook, exportWorkflowNotebookJson, exportWorkflowPythonScript } from "../lib/notebookExport";
import { DatasetIdentityError } from "../lib/datasetIdentity";
import { usePredictiveIdentity } from "../components/PredictiveIdentityProvider";
import { Link } from "react-router-dom";

function downloadText(filename: string, content: string, type: string) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export default function NotebookExport() {
  const [version, setVersion] = useState(0);
  const { readiness, retry } = usePredictiveIdentity();
  const notebookResolution = useMemo(() => {
    if (readiness.status !== "ready") return { notebook: null, error: "" };
    try {
      return { notebook: buildWorkflowNotebook(), error: "" };
    } catch (error) {
      if (error instanceof DatasetIdentityError) {
        return {
          notebook: null,
          error: "The governed notebook cannot be built until the exact registered dataset version is restored.",
        };
      }
      throw error;
    }
  }, [
    readiness.identity?.dataset_id,
    readiness.identity?.dataset_version_id,
    readiness.status,
    version,
  ]);
  const notebook = notebookResolution.notebook;
  if (!notebook) {
    return (
      <section className="rounded-xl border border-amber-200 bg-amber-50 p-6 text-amber-950" data-testid="notebook-export-identity-disabled">
        <h1 className="text-lg font-semibold">Notebook export requires a verified dataset version</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6">{notebookResolution.error || readiness.message}</p>
        <div className="mt-4 flex flex-wrap gap-2">
          <Link to="/step01" className="atlas-primary-button">Open Data Acquisition</Link>
          <button type="button" className="atlas-secondary-button" onClick={retry}>Retry verification</button>
        </div>
      </section>
    );
  }
  const sections = notebook.cells
    .filter((cell) => cell.cell_type === "markdown" && /^## \d+\./.test(cell.source))
    .map((cell) => cell.source.split("\n")[0].replace(/^##\s*/, ""));
  const codeCells = notebook.cells.filter((cell) => cell.cell_type === "code").length;
  const markdownCells = notebook.cells.filter((cell) => cell.cell_type === "markdown").length;

  return (
    <div className="w-full space-y-5">
      <div className="flex flex-col gap-3 pt-2 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <BrandLogo size="md" variant="light" showSubtitle className="mb-3" />
          <div className="flex items-center gap-2">
            <NotebookTabs size={20} className="text-slate-800" />
            <h1 className="text-xl font-semibold text-slate-950">Notebook Export</h1>
          </div>
          <p className="mt-1 max-w-3xl text-sm text-slate-600">
            Export a governed Jupyter notebook that reproduces the workflow from project context through governance
            summary, including generated Python code, decision notes, user-edited code, and output placeholders.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
            onClick={() => setVersion((current) => current + 1)}
          >
            <RefreshCw size={15} />
            Refresh
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800"
            onClick={() =>
              downloadText(
                "modeling-workflow-export.ipynb",
                exportWorkflowNotebookJson(),
                "application/x-ipynb+json;charset=utf-8"
              )
            }
          >
            <Download size={15} />
            Download .ipynb
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800"
            onClick={() =>
              downloadText("modeling-workflow-export.py", exportWorkflowPythonScript(), "text/x-python;charset=utf-8")
            }
          >
            <Download size={15} />
            Download .py
          </button>
        </div>
      </div>

      <section className="grid gap-3 md:grid-cols-3">
        <Stat label="Notebook Sections" value={sections.length} />
        <Stat label="Markdown Cells" value={markdownCells} />
        <Stat label="Code Cells" value={codeCells} />
      </section>

      <section className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-900">
        <div className="font-semibold">Execution note</div>
        <p className="mt-1">
          The notebook is designed as a reproducible handoff. It includes placeholders such as TRAIN.csv, TEST.csv, and
          OOT.csv so the exported file can be moved into a controlled Python environment with governed data paths.
        </p>
      </section>

      <section className="rounded-lg border border-slate-200/80 bg-white/90 shadow-sm">
        <div className="border-b border-slate-200 px-5 py-4">
          <h2 className="text-sm font-semibold text-slate-950">Generated Notebook Outline</h2>
          <p className="mt-1 text-xs text-slate-500">Each section includes markdown explanation, generated code, output placeholder, and matching decision journal notes.</p>
        </div>
        <div className="grid gap-2 p-5 md:grid-cols-2">
          {sections.map((section) => (
            <div key={section} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-medium text-slate-800">
              {section}
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-lg border border-slate-200/80 bg-white/90 p-4 shadow-sm">
        <h2 className="text-sm font-semibold text-slate-950">Notebook JSON Preview</h2>
        <pre className="mt-3 max-h-[520px] overflow-auto rounded-lg bg-slate-950 p-4 text-xs leading-5 text-slate-100">
          {JSON.stringify(notebook, null, 2).slice(0, 12000)}
        </pre>
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-slate-200/80 bg-white/90 p-4 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-2 text-xl font-semibold text-slate-950">{value}</div>
    </div>
  );
}
