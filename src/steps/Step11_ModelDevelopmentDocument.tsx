import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Download, FileText, Printer, RefreshCw } from "lucide-react";
import BrandLogo from "../components/BrandLogo";
import ReportSectionContent from "../components/ReportSectionContent";
import {
  buildModelDevelopmentDocument,
  type ModelDevelopmentDocument,
  type ModelDevelopmentDocumentMode,
} from "../lib/modelDevelopmentDocument";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { upsertProjectFromState } from "../lib/localProjects";

function downloadText(filename: string, text: string, type: string) {
  const blob = new Blob([text], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export default function Step11ModelDevelopmentDocument() {
  const [version, setVersion] = useState(0);
  const [navigationError, setNavigationError] = useState("");
  const [mode, setMode] = useState<ModelDevelopmentDocumentMode>("governance");
  const navigate = useNavigate();
  const markComplete = useWorkflowStore((state) => state.markComplete);
  const document = useMemo<ModelDevelopmentDocument>(() => buildModelDevelopmentDocument(mode), [mode, version]);

  async function handleContinue() {
    try {
      setNavigationError("");
      markComplete("step11");
      await upsertProjectFromState(useWorkflowStore.getState());
      navigate("/step12");
      window.scrollTo({ top: 0, left: 0 });
    } catch (error: any) {
      setNavigationError(error?.message ?? "ATLAS could not save this document step before navigating.");
    }
  }

  return (
    <div className="w-full space-y-5">
      <div className="flex flex-col gap-3 pt-2 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <BrandLogo size="md" variant="light" showSubtitle className="mb-3" />
          <div className="flex items-center gap-2">
            <FileText size={20} className="text-slate-800" />
            <h1 className="text-xl font-semibold text-slate-950">Step 11: Model Development Document</h1>
          </div>
          <p className="mt-1 max-w-3xl text-sm text-slate-600">
            Generate the formal model development document from project context, bureau handling, decisions,
            experiments, evaluation, interpretation, scoring, and reproducibility artifacts.
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
              downloadText(`${document.fileBaseName}.md`, document.markdown, "text/markdown;charset=utf-8")
            }
          >
            <Download size={15} />
            Markdown
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800"
            onClick={() =>
              downloadText(`${document.fileBaseName}.html`, document.html, "text/html;charset=utf-8")
            }
          >
            <Download size={15} />
            HTML
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800"
            onClick={() =>
              downloadText(`${document.fileBaseName}.doc`, document.wordHtml, "application/msword;charset=utf-8")
            }
            title="Exports Word-compatible HTML. True DOCX export requires a DOCX writer dependency."
          >
            <Download size={15} />
            Word .doc
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
            onClick={() => window.print()}
            title="Use the browser print dialog and choose Save as PDF."
          >
            <Printer size={15} />
            Print / PDF
          </button>
        </div>
      </div>

      <section className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-900">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="font-semibold">Documentation package</div>
            <p className="mt-1">
              Choose the right artifact for the audience: executive summary, full governance package, or technical appendix.
              PDF uses the browser print dialog; Word export is Word-compatible HTML.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {([
              ["executive", "Executive Summary"],
              ["governance", "Full Governance Package"],
              ["technical", "Technical Appendix"],
            ] as Array<[ModelDevelopmentDocumentMode, string]>).map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => setMode(value)}
                className={`rounded-lg px-3 py-2 text-xs font-semibold ${
                  mode === value ? "bg-blue-700 text-white shadow-sm" : "border border-blue-200 bg-white text-blue-800 hover:bg-blue-50"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </section>

      <section className="rounded-lg border border-slate-200/80 bg-white/90 shadow-sm">
        <div className="border-b border-slate-200 px-5 py-4">
          <h2 className="text-lg font-semibold text-slate-950">{document.title}</h2>
          <p className="mt-1 text-xs font-medium text-slate-500">
            Generated {new Date(document.generatedAt).toLocaleString()}
          </p>
        </div>

        <div className="grid gap-4 p-5">
          {document.sections.map((section) => (
            <article key={section.number} className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
              <h3 className="text-sm font-semibold text-slate-950">
                {section.number}. {section.title}
              </h3>
              <div className="mt-3">
                <ReportSectionContent content={section.content} />
              </div>
            </article>
          ))}
        </div>
      </section>

      <div className="flex flex-col items-center gap-3 pb-12 pt-2">
        {navigationError && (
          <div className="w-full max-w-2xl rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
            {navigationError}
          </div>
        )}
        <button
          type="button"
          className="rounded-lg bg-indigo-600 px-4 py-2 text-white hover:bg-indigo-700"
          onClick={handleContinue}
        >
          Mark Complete & Continue to Implementation
        </button>
      </div>
    </div>
  );
}
