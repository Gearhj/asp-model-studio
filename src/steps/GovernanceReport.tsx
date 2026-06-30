import { useMemo, useState } from "react";
import { Download, FileText, Printer, RefreshCw } from "lucide-react";
import BrandLogo from "../components/BrandLogo";
import { buildGovernanceReport, type GovernanceReport as GovernanceReportModel } from "../lib/governanceReport";

function downloadText(filename: string, text: string, type: string) {
  const blob = new Blob([text], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export default function GovernanceReport() {
  const [version, setVersion] = useState(0);
  const report = useMemo<GovernanceReportModel>(() => buildGovernanceReport(), [version]);

  return (
    <div className="w-full space-y-5">
      <div className="flex flex-col gap-3 pt-2 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <BrandLogo size="md" variant="light" showSubtitle className="mb-3" />
          <div className="flex items-center gap-2">
            <FileText size={20} className="text-slate-800" />
            <h1 className="text-xl font-semibold text-slate-950">Governance Report</h1>
          </div>
          <p className="mt-1 max-w-3xl text-sm text-slate-600">
            Structured model documentation assembled from project context, decision journal, experiment tracking, and
            captured evaluation evidence.
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
              downloadText(`${report.fileBaseName}.md`, report.markdown, "text/markdown;charset=utf-8")
            }
          >
            <Download size={15} />
            Markdown
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800"
            onClick={() => downloadText(`${report.fileBaseName}.html`, report.html, "text/html;charset=utf-8")}
          >
            <Download size={15} />
            HTML
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800"
            onClick={() =>
              downloadText(`${report.fileBaseName}.doc`, report.wordHtml, "application/msword;charset=utf-8")
            }
            title="Exports Word-compatible HTML. True DOCX export requires adding a DOCX writer dependency."
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
        <div className="font-semibold">Export coverage</div>
        <p className="mt-1">
          Markdown and HTML are exported directly. PDF uses the browser print dialog. The current frontend stack does
          not include a true DOCX writer, so the Word export is a Word-compatible HTML document with a .doc extension.
        </p>
      </section>

      <section className="rounded-lg border border-slate-200/80 bg-white/90 shadow-sm">
        <div className="border-b border-slate-200 px-5 py-4">
          <h2 className="text-lg font-semibold text-slate-950">{report.title}</h2>
          <p className="mt-1 text-xs font-medium text-slate-500">Generated {new Date(report.generatedAt).toLocaleString()}</p>
        </div>

        <div className="grid gap-4 p-5">
          {report.sections.map((section) => (
            <article key={section.number} className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
              <h3 className="text-sm font-semibold text-slate-950">
                {section.number}. {section.title}
              </h3>
              <pre className="mt-3 whitespace-pre-wrap break-words font-sans text-sm leading-6 text-slate-700">
                {section.content}
              </pre>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
