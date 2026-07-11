import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowDown,
  ArrowUp,
  BarChart3,
  Bot,
  Code2,
  Copy,
  Database,
  Download,
  Eye,
  FileText,
  Image as ImageIcon,
  NotebookTabs,
  Paperclip,
  Play,
  Plus,
  RefreshCw,
  Save,
  ShieldCheck,
  Trash2,
  Wand2,
} from "lucide-react";
import {
  getDatasetPreview,
  getDatasetProfile,
  listDatasets,
  type DatasetPreview,
  type DatasetProfile,
  type DatasetSummary,
} from "../lib/datasetLibrary";
import { createEvidence } from "../lib/evidenceGraph";
import {
  attachNotebookToDocumentation,
  CELL_TEMPLATE_SNIPPETS,
  createCodeCell,
  createNotebookCell,
  deleteNotebook,
  downloadBlob,
  effectiveCellKind,
  effectiveCellLanguage,
  executionCellType,
  exportNotebookHtml,
  exportNotebookIpynb,
  getNotebook,
  listNotebooks,
  notebookTemplateCells,
  normalizeNotebook,
  NOTEBOOK_CODE_LANGUAGES,
  runNotebookCell,
  saveNotebook,
  type AtlasNotebook,
  type NotebookCell,
  type NotebookCellOutput,
  type NotebookCodeLanguage,
  type NotebookCellType,
  type NotebookSummary,
} from "../lib/notebookStudio";
import { useWorkflowStore } from "../state/useWorkflowStore";

const TEMPLATE_OPTIONS = [
  { id: "blank", label: "Blank governed notebook" },
  { id: "eda", label: "EDA and profile review" },
  { id: "model-review", label: "Model review evidence" },
  { id: "governance", label: "Governance appendix" },
];

const ASSISTANT_QUICK_PROMPTS = [
  "Create a histogram for the target.",
  "Create a scatter plot of the strongest feature vs target.",
  "Create a correlation heatmap.",
  "Summarize missing values.",
  "Create a group summary table.",
  "Write markdown findings for the latest output.",
  "Explain this error.",
  "Convert this Python analysis to SAS-compatible code.",
  "Convert this SQL result to a chart.",
];

function emptyNotebook(projectId: string, projectName: string, dataset?: DatasetSummary): AtlasNotebook {
  const latestVersion = dataset?.latestVersion?.versionId || "";
  return {
    name: `${projectName || "ATLAS"} Notebook`,
    description: "Governed ATLAS notebook artifact.",
    projectId,
    projectName,
    primaryDatasetId: dataset?.datasetId || "",
    primaryVersionId: latestVersion,
    tags: ["atlas", "governed-notebook"],
    defaultCodeLanguage: "python",
    cells: notebookTemplateCells("blank", "python"),
  };
}

const LANGUAGE_LABELS: Record<NotebookCodeLanguage, string> = {
  python: "Python",
  sql: "SQL",
  r: "R",
  sas_compatible: "SAS-compatible",
};

const TEMPLATE_GROUP_BY_LANGUAGE: Record<NotebookCodeLanguage, string> = {
  python: "Python",
  sql: "SQL",
  r: "R",
  sas_compatible: "SAS",
};

function codeLanguageLabel(language: NotebookCodeLanguage) {
  return LANGUAGE_LABELS[language] || "Python";
}

function statusClass(status?: string) {
  if (status === "success") return "border-emerald-200 bg-emerald-50 text-emerald-800";
  if (status === "error" || status === "failed") return "border-red-200 bg-red-50 text-red-800";
  if (status === "running") return "border-blue-200 bg-blue-50 text-blue-800";
  return "border-slate-200 bg-slate-50 text-slate-600";
}

function outputStatus(output?: NotebookCellOutput) {
  return output?.status || (output?.ok ? "success" : "idle");
}

function filenameFor(notebook: AtlasNotebook, extension: string) {
  const base = (notebook.name || "atlas-notebook").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "atlas-notebook";
  return `${base}.${extension}`;
}

function markdownPreview(source: string) {
  return source
    .split("\n")
    .map((line, index) => {
      const key = `${index}-${line}`;
      if (line.startsWith("### ")) return <h4 key={key} className="mt-3 text-sm font-semibold text-slate-900">{line.slice(4)}</h4>;
      if (line.startsWith("## ")) return <h3 key={key} className="mt-4 text-base font-semibold text-slate-950">{line.slice(3)}</h3>;
      if (line.startsWith("# ")) return <h2 key={key} className="mt-4 text-lg font-semibold text-slate-950">{line.slice(2)}</h2>;
      if (line.startsWith("- ")) return <li key={key} className="ml-5 list-disc text-sm leading-6 text-slate-700">{line.slice(2)}</li>;
      if (!line.trim()) return <div key={key} className="h-2" />;
      return <p key={key} className="text-sm leading-6 text-slate-700">{line}</p>;
    });
}

function downloadText(value: string, filename: string, mimeType = "text/plain") {
  const blob = new Blob([value], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function downloadDataUri(dataUri: string, filename: string) {
  const link = document.createElement("a");
  link.href = dataUri;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function rowsToCsv(rows: Array<Record<string, unknown>>, columns: string[]) {
  const escapeCell = (value: unknown) => `"${String(value ?? "").replace(/"/g, '""')}"`;
  return [columns.map(escapeCell).join(","), ...rows.map((row) => columns.map((column) => escapeCell(row[column])).join(","))].join("\n");
}

function numericValue(value: unknown) {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function SqlResultVisualization({ rows, columns }: { rows: Array<Record<string, unknown>>; columns: string[] }) {
  const [chartType, setChartType] = useState("bar");
  if (!rows.length || !columns.length) return null;
  const numericColumns = columns.filter((column) => rows.some((row) => numericValue(row[column]) !== null));
  const categoryColumn = columns.find((column) => !numericColumns.includes(column)) || columns[0];
  const valueColumn = numericColumns[0] || columns[1] || columns[0];
  const chartRows = rows.slice(0, 24);
  const values = chartRows.map((row) => numericValue(row[valueColumn]) ?? 0);
  const max = Math.max(...values.map((value) => Math.abs(value)), 1);
  return (
    <div className="mt-3 rounded-xl border border-blue-100 bg-white p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-blue-700">
          <BarChart3 size={14} /> Visualize Result
        </div>
        <select value={chartType} onChange={(event) => setChartType(event.target.value)} className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs">
          <option value="bar">Bar</option>
          <option value="line">Line</option>
          <option value="histogram">Histogram</option>
          <option value="scatter">Scatter</option>
        </select>
      </div>
      <svg viewBox="0 0 640 220" className="mt-3 h-56 w-full rounded-lg bg-slate-50">
        <line x1="44" y1="180" x2="610" y2="180" stroke="#cbd5e1" />
        <line x1="44" y1="18" x2="44" y2="180" stroke="#cbd5e1" />
        {chartType === "line" && (
          <polyline
            fill="none"
            stroke="#2563eb"
            strokeWidth="3"
            points={values.map((value, index) => `${60 + index * (530 / Math.max(values.length - 1, 1))},${180 - (Math.abs(value) / max) * 145}`).join(" ")}
          />
        )}
        {chartType === "scatter" && values.map((value, index) => (
          <circle key={index} cx={60 + index * (530 / Math.max(values.length - 1, 1))} cy={180 - (Math.abs(value) / max) * 145} r="4" fill="#0f766e" opacity="0.75" />
        ))}
        {(chartType === "bar" || chartType === "histogram") && values.map((value, index) => {
          const width = Math.max(5, 520 / Math.max(values.length, 1) - 4);
          const height = (Math.abs(value) / max) * 145;
          return <rect key={index} x={56 + index * (530 / Math.max(values.length, 1))} y={180 - height} width={width} height={height} rx="3" fill={chartType === "histogram" ? "#0891b2" : "#2563eb"} opacity="0.82" />;
        })}
      </svg>
      <p className="mt-2 text-xs text-slate-500">Preview chart uses `{categoryColumn}` and `{valueColumn}` from capped result rows.</p>
    </div>
  );
}

function NotebookOutputRenderer({ output, cellType, executionLabel }: { output?: NotebookCellOutput; cellType: NotebookCellType; executionLabel: string }) {
  const rows = output?.rows || output?.tables?.[0]?.rows || [];
  const columns = output?.columns || output?.tables?.[0]?.columns || Object.keys(rows[0] || {}).slice(0, 12);
  const images = output?.images || [];
  const csv = Array.isArray(rows) && rows.length ? rowsToCsv(rows as Array<Record<string, unknown>>, columns.map(String)) : "";
  return (
    <div className={`mt-3 rounded-xl border p-3 ${statusClass(outputStatus(output))}`}>
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs font-semibold uppercase tracking-wide">
        <span>{executionLabel}</span>
        <span>{outputStatus(output)} - {output?.runtimeMs ?? 0} ms - return code {output?.returnCode ?? (outputStatus(output) === "success" ? 0 : "-")}</span>
      </div>
      {output?.truncated && <p className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">ATLAS compacted this output for persistence. Full warehouse-scale output capture is deferred.</p>}
      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <pre className="min-h-[72px] overflow-auto rounded-lg bg-slate-950 p-3 text-xs leading-5 text-slate-100">{output?.stdout || output?.listing || "No stdout captured."}</pre>
        <pre className="min-h-[72px] overflow-auto rounded-lg bg-white p-3 text-xs leading-5 text-red-700">{output?.stderr || output?.error || output?.log || "No stderr captured."}</pre>
      </div>
      {!!output?.html && <div className="mt-3 rounded-lg border border-slate-200 bg-white p-3 text-xs text-slate-700">{output.html}</div>}
      {images.length > 0 && (
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          {images.map((image, index) => {
            const src = `data:${image.mimeType || "image/png"};base64,${image.data}`;
            return (
              <figure key={`${image.alt || "image"}-${index}`} className="rounded-xl border border-slate-200 bg-white p-3">
                <img src={src} alt={image.alt || "ATLAS notebook chart"} className="max-h-[420px] w-full rounded-lg object-contain" />
                <figcaption className="mt-2 flex items-center justify-between gap-2 text-xs text-slate-500">
                  <span>{image.alt || `Notebook chart ${index + 1}`}</span>
                  <span className="flex flex-wrap gap-2">
                    <button type="button" onClick={() => downloadDataUri(src, `atlas-notebook-chart-${index + 1}.png`)} className="rounded-lg border border-slate-300 px-2 py-1 font-semibold text-slate-700">Download PNG</button>
                    <Link to="/model-document-studio" className="rounded-lg border border-emerald-300 px-2 py-1 font-semibold text-emerald-700">Attach Chart to Documentation</Link>
                    <Link to="/chart-studio" className="rounded-lg border border-blue-300 px-2 py-1 font-semibold text-blue-700">Send Chart to Chart Studio</Link>
                  </span>
                </figcaption>
              </figure>
            );
          })}
        </div>
      )}
      {cellType === "python" && outputStatus(output) === "success" && images.length === 0 && (
        <p className="mt-3 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">
          No chart image was captured. Make sure matplotlib is imported and `plt.show()` is called.
        </p>
      )}
      {Array.isArray(rows) && rows.length > 0 && (
        <div className="mt-3 overflow-auto rounded-lg border border-slate-200 bg-white">
          <div className="sticky left-0 top-0 z-10 flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 bg-white px-3 py-2">
            <span className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-600"><Database size={14} /> Table Output</span>
            <div className="flex gap-2">
              <button type="button" onClick={() => downloadText(csv, "atlas-notebook-table.csv", "text/csv")} className="rounded-lg border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-700">Export Table to Excel</button>
              <Link to="/datasets" className="rounded-lg border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-700">Register Table as Dataset</Link>
              <Link to="/chart-studio" className="rounded-lg border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-700">Send table to Chart Studio</Link>
            </div>
          </div>
          <table className="min-w-full text-left text-xs">
            <thead className="sticky top-0 bg-slate-50 text-slate-500">
              <tr>{columns.slice(0, 12).map((column) => <th key={String(column)} className="px-3 py-2 font-semibold">{String(column)}</th>)}</tr>
            </thead>
            <tbody>
              {rows.slice(0, 50).map((row, index) => (
                <tr key={index} className="border-t border-slate-100 odd:bg-white even:bg-slate-50/70">
                  {columns.slice(0, 12).map((column) => <td key={String(column)} className="px-3 py-2 text-slate-700">{String((row as Record<string, unknown>)[String(column)] ?? "")}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {cellType === "sql" && Array.isArray(rows) && rows.length > 0 && <SqlResultVisualization rows={rows as Array<Record<string, unknown>>} columns={columns.map(String)} />}
      {!!output?.translatedPython && (
        <details className="mt-3 rounded-lg border border-slate-200 bg-white p-3">
          <summary className="cursor-pointer text-xs font-semibold text-slate-700">Translated Python</summary>
          <pre className="mt-2 whitespace-pre-wrap text-xs text-slate-700">{output.translatedPython}</pre>
        </details>
      )}
    </div>
  );
}

export default function NotebookStudio() {
  const [searchParams] = useSearchParams();
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [notebooks, setNotebooks] = useState<NotebookSummary[]>([]);
  const [notebook, setNotebook] = useState<AtlasNotebook | null>(null);
  const [profile, setProfile] = useState<DatasetProfile | null>(null);
  const [preview, setPreview] = useState<DatasetPreview | null>(null);
  const [selectedNotebookId, setSelectedNotebookId] = useState("");
  const [selectedDatasetId, setSelectedDatasetId] = useState(searchParams.get("datasetId") || "");
  const [selectedVersionId, setSelectedVersionId] = useState(searchParams.get("versionId") || "");
  const [templateId, setTemplateId] = useState("blank");
  const [librarySearch, setLibrarySearch] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [runningCellId, setRunningCellId] = useState("");
  const [saving, setSaving] = useState(false);
  const [previewMarkdownCells, setPreviewMarkdownCells] = useState<Record<string, boolean>>({});
  const [executionCounter, setExecutionCounter] = useState(1);
  const [dirty, setDirty] = useState(false);
  const [pendingFocusCellId, setPendingFocusCellId] = useState("");
  const [openInsertAfterCellId, setOpenInsertAfterCellId] = useState<string | null>(null);
  const [showTopTemplates, setShowTopTemplates] = useState(false);
  const [showAllTemplateLanguages, setShowAllTemplateLanguages] = useState(false);
  const [continueOnError, setContinueOnError] = useState(false);
  const [runAllProgress, setRunAllProgress] = useState("");
  const [assistantCellId, setAssistantCellId] = useState("");
  const [assistantInstruction, setAssistantInstruction] = useState("");
  const [assistantSuggestion, setAssistantSuggestion] = useState("");
  const [assistantMessage, setAssistantMessage] = useState("Local deterministic assistant. Connect ATLAS_LLM_ENDPOINT to enable live LLM coding help.");
  const cellRefs = useRef<Record<string, HTMLTextAreaElement | null>>({});

  const selectedDataset = useMemo(() => datasets.find((dataset) => dataset.datasetId === selectedDatasetId), [datasets, selectedDatasetId]);
  const defaultCodeLanguage: NotebookCodeLanguage = notebook?.defaultCodeLanguage || "python";
  const selectedAssistantCell = useMemo(() => (notebook?.cells || []).find((cell) => cell.cellId === assistantCellId) || null, [notebook?.cells, assistantCellId]);
  const visibleTemplates = useMemo(() => {
    const selectedGroup = TEMPLATE_GROUP_BY_LANGUAGE[defaultCodeLanguage];
    return CELL_TEMPLATE_SNIPPETS.filter((template) => template.group === "Markdown" || template.group === selectedGroup || showAllTemplateLanguages);
  }, [defaultCodeLanguage, showAllTemplateLanguages]);
  const filteredNotebooks = useMemo(
    () => notebooks.filter((item) => `${item.name} ${item.projectName} ${item.primaryDatasetId}`.toLowerCase().includes(librarySearch.toLowerCase())),
    [notebooks, librarySearch]
  );

  useEffect(() => {
    refreshWorkspace();
  }, []);

  useEffect(() => {
    if (selectedDatasetId && !selectedVersionId) {
      const latestVersion = datasets.find((dataset) => dataset.datasetId === selectedDatasetId)?.latestVersion?.versionId || "";
      if (latestVersion) setSelectedVersionId(latestVersion);
    }
  }, [datasets, selectedDatasetId, selectedVersionId]);

  useEffect(() => {
    loadDatasetContext();
  }, [selectedDatasetId, selectedVersionId]);

  useEffect(() => {
    if (!pendingFocusCellId) return;
    window.setTimeout(() => {
      const target = cellRefs.current[pendingFocusCellId];
      target?.scrollIntoView({ behavior: "smooth", block: "center" });
      target?.focus();
      setPendingFocusCellId("");
    }, 80);
  }, [pendingFocusCellId, notebook?.cells.length]);

  async function refreshWorkspace() {
    setLoading(true);
    setError("");
    try {
      const datasetPayload = await listDatasets();
      setDatasets(datasetPayload.datasets);
      const loadedNotebooks = await listNotebooks();
      setNotebooks(loadedNotebooks);
      const queryNotebook = searchParams.get("notebookId") || "";
      if (queryNotebook) {
        await openNotebook(queryNotebook);
      } else if (!notebook) {
        const queryDataset = datasetPayload.datasets.find((dataset) => dataset.datasetId === selectedDatasetId) || datasetPayload.datasets[0];
        const draft = normalizeNotebook(emptyNotebook(projectId, projectName, queryDataset));
        if (selectedDatasetId) draft.primaryDatasetId = selectedDatasetId;
        if (selectedVersionId) draft.primaryVersionId = selectedVersionId;
        setNotebook(draft);
        if (!selectedDatasetId && queryDataset) {
          setSelectedDatasetId(queryDataset.datasetId);
          setSelectedVersionId(queryDataset.latestVersion?.versionId || "");
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "ATLAS could not load Notebook Studio.");
    } finally {
      setLoading(false);
    }
  }

  async function loadDatasetContext() {
    if (!selectedDatasetId || !selectedVersionId) return;
    try {
      const [profilePayload, previewPayload] = await Promise.all([getDatasetProfile(selectedDatasetId, selectedVersionId), getDatasetPreview(selectedDatasetId, selectedVersionId)]);
      setProfile(profilePayload.profile);
      setPreview(previewPayload);
      setNotebook((current) => current ? normalizeNotebook({ ...current, primaryDatasetId: selectedDatasetId, primaryVersionId: selectedVersionId }) : current);
    } catch (err) {
      setError(err instanceof Error ? err.message : "ATLAS could not load dataset context.");
    }
  }

  async function openNotebook(notebookId: string) {
    setError("");
    const loaded = normalizeNotebook(await getNotebook(notebookId));
    setNotebook(loaded);
    setSelectedNotebookId(loaded.notebookId || "");
    setSelectedDatasetId(loaded.primaryDatasetId || selectedDatasetId);
    setSelectedVersionId(loaded.primaryVersionId || selectedVersionId);
  }

  async function persistNotebook(current = notebook): Promise<AtlasNotebook | null> {
    if (!current) return null;
    setSaving(true);
    setError("");
    try {
      const saved = normalizeNotebook(await saveNotebook({
        ...current,
        projectId,
        projectName,
        primaryDatasetId: selectedDatasetId,
        primaryVersionId: selectedVersionId,
      }));
      setNotebook(saved);
      setSelectedNotebookId(saved.notebookId || "");
      setNotebooks(await listNotebooks());
      setMessage("Notebook saved.");
      setDirty(false);
      return saved;
    } catch (err) {
      setError(err instanceof Error ? err.message : "ATLAS could not save this notebook.");
      return null;
    } finally {
      setSaving(false);
    }
  }

  async function createNotebookFromTemplate(template = templateId) {
    const draft = emptyNotebook(projectId, projectName, selectedDataset);
    draft.name = `${projectName || "ATLAS"} - ${TEMPLATE_OPTIONS.find((item) => item.id === template)?.label || "Notebook"}`;
    draft.defaultCodeLanguage = defaultCodeLanguage;
    draft.cells = notebookTemplateCells(template, defaultCodeLanguage);
    const saved = await persistNotebook(draft);
    if (saved) setMessage("Notebook created.");
  }

  function updateCell(cellId: string, patch: Partial<NotebookCell>) {
    setNotebook((current) => current ? { ...current, cells: current.cells.map((cell) => (cell.cellId === cellId ? { ...cell, ...patch } : cell)) } : current);
    setDirty(true);
  }

  function setDefaultCodeLanguage(language: NotebookCodeLanguage) {
    setNotebook((current) => current ? normalizeNotebook({ ...current, defaultCodeLanguage: language }) : current);
    setDirty(true);
    setMessage(`Default Code Language set to ${codeLanguageLabel(language)}. Existing code cells keep their language unless changed.`);
  }

  function addNotebookCell(kind: "markdown" | "code") {
    try {
      const newCell = kind === "markdown" ? createNotebookCell("markdown") : createCodeCell(defaultCodeLanguage);
      setNotebook((current) => current ? { ...current, cells: [...current.cells, newCell] } : current);
      setPendingFocusCellId(newCell.cellId);
      setDirty(true);
      setMessage(kind === "markdown" ? "Markdown cell added." : `Code cell added using ${codeLanguageLabel(defaultCodeLanguage)}.`);
    } catch (err) {
      setError(`Could not add cell: ${err instanceof Error ? err.message : "Unknown error"}`);
    }
  }

  function addCellBelow(cellId: string, kind: "markdown" | "code" = "code", source?: string, language: NotebookCodeLanguage = defaultCodeLanguage) {
    try {
      const newCell = kind === "markdown" ? createNotebookCell("markdown", source) : createCodeCell(language, source);
      setNotebook((current) => {
        if (!current) return current;
        const index = current.cells.findIndex((cell) => cell.cellId === cellId);
        const cells = [...current.cells];
        cells.splice((index >= 0 ? index : cells.length - 1) + 1, 0, newCell);
        return { ...current, cells };
      });
      setPendingFocusCellId(newCell.cellId);
      setDirty(true);
      setOpenInsertAfterCellId(null);
      setMessage(kind === "markdown" ? "Markdown cell inserted." : `Code cell inserted using ${codeLanguageLabel(language)}.`);
    } catch (err) {
      setError(`Could not add cell: ${err instanceof Error ? err.message : "Unknown error"}`);
    }
  }

  function addTemplateCell(template: (typeof CELL_TEMPLATE_SNIPPETS)[number]) {
    const kind = template.cellType === "markdown" ? "markdown" : "code";
    const newCell = kind === "markdown" ? createNotebookCell("markdown", template.source) : createCodeCell(template.cellType as NotebookCodeLanguage, template.source);
    setNotebook((current) => current ? { ...current, cells: [...current.cells, newCell] } : current);
    setPendingFocusCellId(newCell.cellId);
    setDirty(true);
    setMessage(`${template.label} template inserted.`);
  }

  function duplicateCell(cell: NotebookCell) {
    const kind = effectiveCellKind(cell);
    const language = effectiveCellLanguage(cell, defaultCodeLanguage);
    setNotebook((current) => current ? { ...current, cells: [...current.cells, kind === "markdown" ? createNotebookCell("markdown", cell.source) : createCodeCell(language, cell.source)] } : current);
    setDirty(true);
  }

  function removeCell(cellId: string) {
    setNotebook((current) => current ? { ...current, cells: current.cells.filter((cell) => cell.cellId !== cellId) } : current);
    setDirty(true);
  }

  function moveCell(cellId: string, direction: -1 | 1) {
    setNotebook((current) => {
      if (!current) return current;
      const index = current.cells.findIndex((cell) => cell.cellId === cellId);
      const nextIndex = index + direction;
      if (index < 0 || nextIndex < 0 || nextIndex >= current.cells.length) return current;
      const cells = [...current.cells];
      [cells[index], cells[nextIndex]] = [cells[nextIndex], cells[index]];
      return { ...current, cells };
    });
    setDirty(true);
  }

  function clearCellOutput(cellId: string) {
    updateCell(cellId, { output: { status: "idle" }, lastRunAt: "" });
  }

  function updateCellLanguage(cellId: string, language: NotebookCodeLanguage) {
    updateCell(cellId, { cellKind: "code", language, cellType: language });
    setMessage(`Cell language changed to ${codeLanguageLabel(language)}. Notebook default remains ${codeLanguageLabel(defaultCodeLanguage)}.`);
  }

  async function runCell(cell: NotebookCell) {
    const saved = await persistNotebook();
    if (!saved?.notebookId) return;
    setRunningCellId(cell.cellId);
    try {
      const executionCell = { ...cell, cellType: executionCellType(cell, saved.defaultCodeLanguage || defaultCodeLanguage) };
      const result = await runNotebookCell(saved.notebookId, executionCell, { ...saved, primaryDatasetId: selectedDatasetId, primaryVersionId: selectedVersionId });
      updateCell(cell.cellId, { output: { ...result.output, executionCount: executionCounter }, lastRunAt: new Date().toISOString() });
      setExecutionCounter((current) => current + 1);
      setMessage(result.ok ? "Cell executed." : "Cell execution finished with errors.");
    } catch (err) {
      updateCell(cell.cellId, { output: { status: "error", stderr: err instanceof Error ? err.message : "ATLAS could not run this cell.", runtimeMs: 0, returnCode: 1 } });
    } finally {
      setRunningCellId("");
    }
  }

  async function runAllCells() {
    const saved = await persistNotebook();
    if (!saved?.notebookId) return;
    setLoading(true);
    setRunAllProgress("Starting notebook run...");
    try {
      let workingNotebook = saved;
      for (let index = 0; index < workingNotebook.cells.length; index += 1) {
        const cell = workingNotebook.cells[index];
        setRunAllProgress(`Running cell ${index + 1} of ${workingNotebook.cells.length}`);
        if (effectiveCellKind(cell) === "markdown") {
          const output = { status: "success", stdout: "Markdown preview rendered.", stderr: "", runtimeMs: 0, returnCode: 0, executionCount: executionCounter + index };
          workingNotebook = { ...workingNotebook, cells: workingNotebook.cells.map((candidate) => candidate.cellId === cell.cellId ? { ...candidate, output, lastRunAt: new Date().toISOString() } : candidate) };
          setNotebook(workingNotebook);
          continue;
        }
        const executionCell = { ...cell, cellType: executionCellType(cell, workingNotebook.defaultCodeLanguage || defaultCodeLanguage) };
        const result = await runNotebookCell(workingNotebook.notebookId || saved.notebookId, executionCell, { ...workingNotebook, primaryDatasetId: selectedDatasetId, primaryVersionId: selectedVersionId });
        const output = { ...result.output, executionCount: executionCounter + index };
        workingNotebook = { ...workingNotebook, cells: workingNotebook.cells.map((candidate) => candidate.cellId === cell.cellId ? { ...candidate, output, lastRunAt: new Date().toISOString() } : candidate) };
        setNotebook(workingNotebook);
        if (!result.ok && !continueOnError) {
          setRunAllProgress(`Stopped at cell ${index + 1} because it returned an error.`);
          setMessage("Notebook run stopped on error.");
          return;
        }
      }
      setExecutionCounter((current) => current + workingNotebook.cells.length);
      setNotebook(await saveNotebook(workingNotebook));
      setMessage("Notebook run complete.");
      setRunAllProgress("Notebook run complete.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "ATLAS could not run this notebook.");
    } finally {
      setLoading(false);
    }
  }

  async function exportIpynb() {
    const saved = await persistNotebook();
    if (!saved?.notebookId) return;
    downloadBlob(await exportNotebookIpynb(saved.notebookId), filenameFor(saved, "ipynb"));
  }

  async function exportHtml() {
    const saved = await persistNotebook();
    if (!saved?.notebookId) return;
    downloadBlob(await exportNotebookHtml(saved.notebookId), filenameFor(saved, "html"));
  }

  async function attachEvidence() {
    const saved = await persistNotebook();
    if (!saved?.notebookId) return;
    await attachNotebookToDocumentation({ notebookId: saved.notebookId, projectId, sectionId: "appendices", summary: "Notebook output attached from ATLAS Notebook Studio." });
    setMessage("Notebook output attached to documentation evidence.");
  }

  async function saveNotebookOutputAsEvidence() {
    const saved = await persistNotebook();
    if (!saved?.notebookId) return;
    const outputCount = saved.cells.filter((cell) => cell.output).length;
    await createEvidence({
      projectId,
      projectName,
      evidenceType: "notebook",
      title: `Notebook Output: ${saved.name}`,
      summary: `${outputCount} executed notebook output(s) captured as governed evidence reference.`,
      sourcePage: "Notebook Studio",
      sourceRoute: `/notebook-studio?notebookId=${saved.notebookId}`,
      artifactType: "notebook",
      artifactId: saved.notebookId,
      datasetIds: saved.primaryDatasetId ? [saved.primaryDatasetId] : [],
      notebookIds: [saved.notebookId],
      supportsSections: ["Appendix", "Reproducibility", "Model Diagnostics"],
      tags: ["governance", "model_risk"],
      status: outputCount ? "ready" : "needs_review",
      importance: "medium",
      lineage: { primaryDatasetId: saved.primaryDatasetId, primaryVersionId: saved.primaryVersionId, outputCount },
      governance: { note: "Notebook output is referenced by notebook ID; full notebook remains in Notebook Studio." },
    });
    setMessage("Notebook output saved to the Model Evidence Center.");
  }

  function openAssistantForCell(cell: NotebookCell, instruction = "") {
    setAssistantCellId(cell.cellId);
    setAssistantInstruction(instruction);
    setAssistantSuggestion("");
    setAssistantMessage("Local deterministic assistant. Connect ATLAS_LLM_ENDPOINT to enable live LLM coding help.");
  }

  function deterministicAssistantSuggestion(action: "explain" | "fix" | "chart" | "summary" | "next") {
    const cell = selectedAssistantCell;
    const language = defaultCodeLanguage;
    const columns = datasetColumns.slice(0, 12);
    const target = columns.find((column) => /target|class|medhouseval|actual/i.test(column)) || columns[columns.length - 1] || "target";
    const firstNumeric = columns.find((column) => /amount|inc|value|score|rate|age|time|v\d+/i.test(column)) || columns[0] || "column";
    const secondNumeric = columns.find((column) => column !== firstNumeric && /value|score|rate|v\d+|age|inc/i.test(column)) || target;
    if (action === "explain") {
      return `## Cell Explanation\n\nThis ${effectiveCellKind(cell || { cellType: "markdown" }) === "markdown" ? "Markdown" : `Code: ${codeLanguageLabel(effectiveCellLanguage(cell || { cellType: language }, language))}`} cell uses the selected Dataset Library preview rows. Review stdout, tables, and chart outputs as exploratory evidence, then attach material outputs to Model Documentation Studio.`;
    }
    if (action === "fix") {
      if (language === "sql") return `-- Check table alias and column names before re-running.\nSELECT *\nFROM REG_TRAIN\nLIMIT 25;`;
      if (language === "sas_compatible") return `proc contents data=work.primary;\nrun;\n\nproc means data=work.primary n mean median std min max;\nrun;`;
      if (language === "r") return `print("Check the available preview dataframe")\nprint(dim(df))\nprint(head(df))`;
      return `import pandas as pd\nimport matplotlib.pyplot as plt\n\ndf = pd.DataFrame(preview_rows)\nprint('Rows, columns:', df.shape)\nprint(df.head())\n# If your prior cell failed, confirm column names first:\nprint(df.columns.tolist())`;
    }
    if (action === "summary") {
      return `## Findings Summary\n\n- Dataset reviewed: ${selectedDataset?.name || "selected Dataset Library asset"}.\n- Current cell status: ${outputStatus(cell?.output)}.\n- Key evidence: summarize the latest table, chart, warning, or error here.\n- Governance note: outputs use preview/sample rows unless full artifact execution is enabled.`;
    }
    if (action === "next") {
      if (language === "sql") return `SELECT *\nFROM REG_TRAIN\nLIMIT 100;`;
      if (language === "sas_compatible") return `proc freq data=work.primary;\nrun;`;
      if (language === "r") return `print(summary(df))`;
      return `import pandas as pd\n\ndf = pd.DataFrame(preview_rows)\nsummary = df.describe(include='all').transpose()\natlas_display(summary.head(25), title='Profile summary')`;
    }
    if (language === "sql") {
      return `SELECT ${firstNumeric}, ${target}, COUNT(*) AS records\nFROM REG_TRAIN\nGROUP BY ${firstNumeric}, ${target}\nORDER BY records DESC\nLIMIT 100;`;
    }
    if (language === "sas_compatible") {
      return `proc means data=work.primary n mean median std min max;\nrun;\n\nproc freq data=work.primary;\nrun;\n/* For chart rendering, send summarized output to Chart Studio or use a Python chart cell. */`;
    }
    if (language === "r") {
      return `print("ATLAS R chart guidance")\nprint(summary(df))\n# R image capture is environment-dependent in this phase; use Chart Studio for governed visuals.`;
    }
    return `import pandas as pd\nimport matplotlib.pyplot as plt\n\ndf = pd.DataFrame(preview_rows)\n\ncolumn = '${target}' if '${target}' in df.columns else '${firstNumeric}'\ndf[column].dropna().hist(bins=20)\nplt.title(f'Distribution of {column}')\nplt.xlabel(column)\nplt.ylabel('Count')\nplt.show()\n\n# Alternative scatter if two numeric columns are available:\n# x = '${firstNumeric}'\n# y = '${secondNumeric}'\n# plt.figure(figsize=(7,4))\n# plt.scatter(df[x], df[y], alpha=0.7)\n# plt.title(f'{y} vs {x}')\n# plt.xlabel(x)\n# plt.ylabel(y)\n# plt.show()`;
  }

  function runAssistantAction(action: "explain" | "fix" | "chart" | "summary" | "next") {
    const suggestion = deterministicAssistantSuggestion(action);
    setAssistantSuggestion(suggestion);
    setAssistantMessage("Deterministic ATLAS suggestion generated from current cell, dataset schema, and recent output. Live LLM coding help can be enabled with ATLAS_LLM_ENDPOINT.");
  }

  function insertAssistantSuggestion() {
    if (!assistantSuggestion) return;
    const isMarkdown = assistantSuggestion.trim().startsWith("##");
    if (assistantCellId) addCellBelow(assistantCellId, isMarkdown ? "markdown" : "code", assistantSuggestion, defaultCodeLanguage);
    else {
      const newCell = isMarkdown ? createNotebookCell("markdown", assistantSuggestion) : createCodeCell(defaultCodeLanguage, assistantSuggestion);
      setNotebook((current) => current ? { ...current, cells: [...current.cells, newCell] } : current);
      setPendingFocusCellId(newCell.cellId);
      setDirty(true);
    }
  }

  function replaceCurrentCellWithSuggestion() {
    if (assistantSuggestion && assistantCellId) updateCell(assistantCellId, { source: assistantSuggestion });
  }

  async function removeNotebookFromLibrary(notebookId: string) {
    await deleteNotebook(notebookId);
    setNotebooks(await listNotebooks());
    if (selectedNotebookId === notebookId) setSelectedNotebookId("");
  }

  const datasetColumns = profile?.schema?.map((column) => column.name) || preview?.columns || [];
  const outputGallery = useMemo(() => {
    const cells = notebook?.cells || [];
    return {
      charts: cells.filter((cell) => (cell.output?.images || []).length > 0),
      tables: cells.filter((cell) => (cell.output?.rows || cell.output?.tables?.[0]?.rows || []).length > 0),
      messages: cells.filter((cell) => !!(cell.output?.stdout || cell.output?.listing)),
      errors: cells.filter((cell) => outputStatus(cell.output) === "error" || !!(cell.output?.stderr || cell.output?.error || cell.output?.log)),
    };
  }, [notebook?.cells]);

  return (
    <div className="atlas-page-shell atlas-theme-notebook min-h-[calc(100vh-130px)]">
      <section className="atlas-studio-hero">
        <div className="atlas-studio-hero__band">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <div className="flex items-center gap-3">
              <div className="rounded-2xl bg-white/10 p-3 text-sky-200"><NotebookTabs size={24} /></div>
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-sky-200">Notebook workspace</p>
                <h1 className="text-2xl font-semibold tracking-tight text-white">Notebook Studio</h1>
              </div>
            </div>
            <p className="mt-3 max-w-4xl text-sm leading-6 text-sky-50/90">
              Unified governed notebook workspace for ATLAS analysis. Select one default code language, then interleave Markdown and Code cells in a continuous Jupyter-style canvas.
            </p>
            <div className="mt-3 inline-flex flex-wrap items-center gap-2 rounded-xl border border-sky-200 bg-white px-3 py-2 text-sm">
              <span className="font-semibold text-blue-900">Default Code Language</span>
              <select value={defaultCodeLanguage} onChange={(event) => setDefaultCodeLanguage(event.target.value as NotebookCodeLanguage)} className="rounded-lg border border-blue-200 bg-white px-2 py-1 text-sm font-semibold text-blue-950">
                {NOTEBOOK_CODE_LANGUAGES.map((language) => <option key={language.value} value={language.value}>{language.label}</option>)}
              </select>
              <span className="text-xs text-blue-700">New Code cells use {codeLanguageLabel(defaultCodeLanguage)}.</span>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => persistNotebook()} className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800">
              <Save size={16} /> {saving ? "Saving..." : "Save Notebook"}
            </button>
            <label className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700">
              <input type="checkbox" checked={continueOnError} onChange={(event) => setContinueOnError(event.target.checked)} />
              Continue on error
            </label>
            <button type="button" onClick={runAllCells} className="inline-flex items-center gap-2 rounded-lg bg-blue-700 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-800">
              <Play size={16} /> Run All
            </button>
            <button type="button" onClick={exportIpynb} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50">
              <Download size={16} /> Export .ipynb
            </button>
            <button type="button" onClick={exportHtml} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50">
              <FileText size={16} /> Export HTML
            </button>
            <button type="button" onClick={saveNotebookOutputAsEvidence} className="inline-flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm font-semibold text-emerald-800 shadow-sm hover:bg-emerald-100">
              <Paperclip size={16} /> Save Notebook Output to Model Evidence Center
            </button>
            <Link to="/model-evidence-center" className="inline-flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-semibold text-blue-800 shadow-sm hover:bg-blue-100">
              Open Model Evidence Center
            </Link>
          </div>
        </div>
        </div>
        {(message || error) && (
          <div className={`mx-5 my-4 rounded-xl border px-4 py-3 text-sm ${error ? "border-red-200 bg-red-50 text-red-700" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>
            {error || message}
          </div>
        )}
        {(dirty || runAllProgress) && (
          <div className="mx-5 mb-4 flex flex-wrap gap-2 text-xs">
            {dirty && <span className="rounded-full border border-amber-200 bg-amber-50 px-3 py-1 font-semibold text-amber-800">Unsaved changes</span>}
            {runAllProgress && <span className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1 font-semibold text-blue-800">{runAllProgress}</span>}
          </div>
        )}
      </section>

      <div className="grid gap-4 xl:grid-cols-[230px_minmax(0,1fr)_300px]">
        <aside className="space-y-4">
          <section className="rounded-2xl border border-blue-200 bg-white p-4 shadow-sm">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Bot size={16} className="text-blue-700" />
                <h2 className="text-sm font-semibold text-slate-950">Notebook Assistant</h2>
              </div>
              <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-1 text-[10px] font-semibold text-slate-600">Local fallback</span>
            </div>
            <p className="mt-2 text-xs leading-5 text-slate-600">{assistantMessage}</p>
            <div className="mt-3 rounded-xl border border-blue-100 bg-blue-50 p-3 text-xs font-semibold text-blue-800">
              Assistant output language: {codeLanguageLabel(defaultCodeLanguage)}
            </div>
            <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs">
              <div className="font-semibold text-slate-700">Focused cell</div>
              <div className="mt-1 text-slate-500">{selectedAssistantCell ? `${effectiveCellKind(selectedAssistantCell) === "markdown" ? "Markdown" : `Code: ${codeLanguageLabel(effectiveCellLanguage(selectedAssistantCell, defaultCodeLanguage))}`} - ${outputStatus(selectedAssistantCell.output)}` : "Select Ask ATLAS on a cell."}</div>
            </div>
            <textarea value={assistantInstruction} onChange={(event) => setAssistantInstruction(event.target.value)} placeholder="Ask ATLAS to generate code, fix an error, or explain the cell." className="mt-3 min-h-[70px] w-full rounded-xl border border-slate-300 p-2 text-xs" />
            <div className="mt-3 grid grid-cols-2 gap-2">
              <button type="button" onClick={() => runAssistantAction("explain")} className="rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs font-semibold text-slate-700">Explain Current Cell</button>
              <button type="button" onClick={() => runAssistantAction("fix")} className="rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs font-semibold text-slate-700">Fix Error</button>
              <button type="button" onClick={() => runAssistantAction("next")} className="rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs font-semibold text-slate-700">Generate Code Cell</button>
              <button type="button" onClick={() => runAssistantAction("chart")} className="rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs font-semibold text-slate-700">Generate Chart Cell</button>
              <button type="button" onClick={() => runAssistantAction("summary")} className="col-span-2 rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs font-semibold text-slate-700">Generate Markdown Findings</button>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {ASSISTANT_QUICK_PROMPTS.slice(0, 6).map((prompt) => (
                <button key={prompt} type="button" onClick={() => { setAssistantInstruction(prompt); runAssistantAction(prompt.includes("error") ? "fix" : prompt.includes("markdown") || prompt.includes("findings") ? "summary" : "chart"); }} className="rounded-full border border-blue-100 bg-blue-50 px-2 py-1 text-[10px] font-semibold text-blue-800">
                  {prompt}
                </button>
              ))}
            </div>
            {assistantSuggestion && (
              <div className="mt-3 rounded-xl border border-slate-200 bg-slate-950 p-3">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <span className="text-xs font-semibold uppercase tracking-wide text-slate-300">Suggested code / markdown</span>
                  <Wand2 size={14} className="text-blue-300" />
                </div>
                <pre className="max-h-64 overflow-auto whitespace-pre-wrap text-xs leading-5 text-slate-100">{assistantSuggestion}</pre>
                <div className="mt-3 grid grid-cols-2 gap-2">
                  <button type="button" onClick={insertAssistantSuggestion} className="rounded-lg bg-blue-600 px-2 py-1.5 text-xs font-semibold text-white">Insert as New Cell</button>
                  <button type="button" onClick={replaceCurrentCellWithSuggestion} className="rounded-lg border border-slate-600 px-2 py-1.5 text-xs font-semibold text-slate-100">Replace Current Cell</button>
                </div>
              </div>
            )}
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-slate-950">Notebook Library</h2>
              <button type="button" onClick={refreshWorkspace} className="rounded-lg border border-slate-200 p-2 text-slate-600 hover:bg-slate-50" title="Refresh notebooks">
                <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
              </button>
            </div>
            <input value={librarySearch} onChange={(event) => setLibrarySearch(event.target.value)} placeholder="Search notebooks" className="mt-3 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
            <div className="mt-3 flex gap-2">
              <select value={templateId} onChange={(event) => setTemplateId(event.target.value)} className="min-w-0 flex-1 rounded-lg border border-slate-300 bg-white px-2 py-2 text-xs">
                {TEMPLATE_OPTIONS.map((template) => <option key={template.id} value={template.id}>{template.label}</option>)}
              </select>
              <button type="button" onClick={() => createNotebookFromTemplate()} className="rounded-lg bg-blue-700 px-3 py-2 text-xs font-semibold text-white hover:bg-blue-800">Create</button>
            </div>
            <div className="mt-4 max-h-[380px] space-y-2 overflow-auto">
              {filteredNotebooks.map((item) => (
                <div key={item.notebookId} className={`rounded-xl border p-3 text-xs ${selectedNotebookId === item.notebookId ? "border-blue-300 bg-blue-50" : "border-slate-200 bg-slate-50"}`}>
                  <button type="button" onClick={() => openNotebook(item.notebookId)} className="block w-full text-left font-semibold text-slate-900">{item.name}</button>
                  <p className="mt-1 text-slate-500">{item.cellCount} cells - {item.lastRunStatus}</p>
                  <p className="text-slate-500">{item.updatedAt ? new Date(item.updatedAt).toLocaleString() : "Not saved"}</p>
                  <div className="mt-2 flex gap-2">
                    <button type="button" onClick={() => openNotebook(item.notebookId)} className="rounded-lg border border-slate-200 bg-white px-2 py-1 font-semibold text-slate-700">Open</button>
                    <button type="button" onClick={() => removeNotebookFromLibrary(item.notebookId)} className="rounded-lg border border-red-200 bg-white px-2 py-1 font-semibold text-red-700">Delete</button>
                  </div>
                </div>
              ))}
              {!filteredNotebooks.length && <p className="rounded-xl border border-dashed border-slate-300 p-4 text-xs text-slate-500">No saved notebooks yet. Create one from a governed template.</p>}
            </div>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2">
              <Database size={16} className="text-blue-700" />
              <h2 className="text-sm font-semibold text-slate-950">Dataset Context</h2>
            </div>
            <select value={selectedDatasetId} onChange={(event) => { setSelectedDatasetId(event.target.value); setSelectedVersionId(""); }} className="mt-3 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm">
              <option value="">Select dataset</option>
              {datasets.map((dataset) => <option key={dataset.datasetId} value={dataset.datasetId}>{dataset.name}</option>)}
            </select>
            <select value={selectedVersionId} onChange={(event) => setSelectedVersionId(event.target.value)} className="mt-2 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm">
              <option value="">Select version</option>
              {(selectedDataset?.latestVersion ? [selectedDataset.latestVersion] : []).map((version) => <option key={version.versionId} value={version.versionId}>{version.versionId}</option>)}
            </select>
            <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-2"><span className="block text-slate-500">Rows</span><strong>{profile?.rowCount?.toLocaleString() || selectedDataset?.latestVersion?.rowCount?.toLocaleString() || "-"}</strong></div>
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-2"><span className="block text-slate-500">Columns</span><strong>{profile?.columnCount || selectedDataset?.latestVersion?.columnCount || "-"}</strong></div>
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-2"><span className="block text-slate-500">Preview Rows</span><strong>{preview?.rows?.length || 0}</strong></div>
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-2"><span className="block text-slate-500">Role</span><strong>{selectedDataset?.datasetRole || "analysis"}</strong></div>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <Link to={`/datasets/${selectedDatasetId}`} className={`rounded-lg border border-slate-300 px-2 py-1 text-xs font-semibold ${selectedDatasetId ? "text-slate-700" : "pointer-events-none text-slate-300"}`}>Dataset Detail</Link>
              <Link to="/analytics" className="rounded-lg border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-700">Analytics Workbench</Link>
              <Link to="/chart-studio" className="rounded-lg border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-700">Chart Studio</Link>
            </div>
          </section>
        </aside>

        <main className="space-y-4">
          <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_220px]">
              <div>
                <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Notebook Name</label>
                <input value={notebook?.name || ""} onChange={(event) => setNotebook((current) => current ? { ...current, name: event.target.value } : current)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-lg font-semibold text-slate-950" />
              </div>
              <div>
                <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Project</label>
                <div className="mt-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-700">{projectName || "Current ATLAS Project"}</div>
              </div>
            </div>
            <textarea value={notebook?.description || ""} onChange={(event) => setNotebook((current) => current ? { ...current, description: event.target.value } : current)} placeholder="Describe the governed purpose of this notebook." className="mt-3 min-h-[58px] w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold text-slate-950">Notebook Canvas</h2>
                <p className="text-xs text-slate-500">One continuous notebook. Interleave Markdown and Code cells; Code defaults to {codeLanguageLabel(defaultCodeLanguage)}.</p>
              </div>
              <div className="relative flex flex-wrap gap-2">
                <button type="button" onClick={() => addNotebookCell("markdown")} className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50">
                  <Plus size={13} /> + Markdown
                </button>
                <button type="button" onClick={() => addNotebookCell("code")} className="inline-flex items-center gap-1 rounded-lg bg-slate-950 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-800">
                  <Plus size={13} /> + Code
                </button>
                <button type="button" onClick={() => setShowTopTemplates((current) => !current)} className="inline-flex items-center gap-1 rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-semibold text-blue-800 hover:bg-blue-100">
                  <Plus size={13} /> + From Template
                </button>
                {showTopTemplates && (
                  <div className="absolute right-0 top-9 z-30 w-72 rounded-xl border border-slate-200 bg-white p-2 shadow-lg">
                    {visibleTemplates.slice(0, 12).map((template) => (
                      <button key={`top-${template.group}-${template.label}`} type="button" onClick={() => { addTemplateCell(template); setShowTopTemplates(false); }} className="block w-full rounded-lg px-3 py-2 text-left text-xs text-slate-700 hover:bg-blue-50">
                        <span className="font-semibold">{template.group === "Markdown" ? "Markdown" : "Code"}</span>: {template.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>

            <div className="mt-4 space-y-4">
              {(notebook?.cells || []).map((cell, index) => {
                const cellKind = effectiveCellKind(cell);
                const cellLanguage = effectiveCellLanguage(cell, defaultCodeLanguage);
                const displayCellType = executionCellType(cell, defaultCodeLanguage);
                const isMarkdownPreview = !!previewMarkdownCells[cell.cellId];
                const executionLabel = cellKind === "markdown" ? "Out [preview]:" : `Out [${cell.output?.executionCount ?? " "}]:`;
                const isErrorCell = outputStatus(cell.output) === "error" || !!(cell.output?.stderr || cell.output?.error || cell.output?.log);
                return (
                  <div key={cell.cellId}>
                  <article className="rounded-xl border border-slate-200 bg-white shadow-sm">
                    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className="rounded-full bg-slate-900 px-2.5 py-1 text-xs font-semibold uppercase tracking-wide text-white">{cellKind === "markdown" ? "Markdown" : `Code: ${codeLanguageLabel(cellLanguage)}`}</span>
                        <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${statusClass(outputStatus(cell.output))}`}>{outputStatus(cell.output)}</span>
                        {!!cell.lastRunAt && <span className="text-xs text-slate-400">Last run {new Date(cell.lastRunAt).toLocaleTimeString()}</span>}
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {cellKind === "markdown" ? (
                          <button type="button" onClick={() => setPreviewMarkdownCells((current) => ({ ...current, [cell.cellId]: !current[cell.cellId] }))} className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700">
                            <Eye size={13} /> {isMarkdownPreview ? "Edit" : "Preview"}
                          </button>
                        ) : (
                          <button type="button" onClick={() => runCell(cell)} className="inline-flex items-center gap-1 rounded-lg bg-slate-950 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-800">
                            <Play size={13} /> {runningCellId === cell.cellId ? "Running..." : "Run"}
                          </button>
                        )}
                        <button type="button" onClick={() => openAssistantForCell(cell, isErrorCell ? "Explain this error and suggest a fix." : "Suggest the next analysis step.")} className="inline-flex items-center gap-1 rounded-lg border border-blue-200 bg-blue-50 px-2 py-1.5 text-xs font-semibold text-blue-800">
                          <Bot size={13} /> {isErrorCell ? "Fix with ATLAS" : "Ask ATLAS"}
                        </button>
                        {cellKind === "code" && (
                          <label className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs font-semibold text-slate-700">
                            Language:
                            <select value={cellLanguage} onChange={(event) => updateCellLanguage(cell.cellId, event.target.value as NotebookCodeLanguage)} className="bg-white text-xs">
                              {NOTEBOOK_CODE_LANGUAGES.map((language) => <option key={language.value} value={language.value}>{language.label}</option>)}
                            </select>
                          </label>
                        )}
                        <button type="button" onClick={() => addCellBelow(cell.cellId, "code")} className="rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs font-semibold text-slate-700">Add below</button>
                        <button type="button" onClick={() => clearCellOutput(cell.cellId)} className="rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs font-semibold text-slate-700">Clear output</button>
                        <button type="button" onClick={() => navigator.clipboard?.writeText(cell.source)} className="rounded-lg border border-slate-300 bg-white p-1.5 text-slate-600" title="Copy code"><Copy size={14} /></button>
                        <button type="button" onClick={() => moveCell(cell.cellId, -1)} className="rounded-lg border border-slate-300 bg-white p-1.5 text-slate-600" title="Move up"><ArrowUp size={14} /></button>
                        <button type="button" onClick={() => moveCell(cell.cellId, 1)} className="rounded-lg border border-slate-300 bg-white p-1.5 text-slate-600" title="Move down"><ArrowDown size={14} /></button>
                        <button type="button" onClick={() => duplicateCell(cell)} className="rounded-lg border border-slate-300 bg-white p-1.5 text-slate-600" title="Duplicate"><Plus size={14} /></button>
                        <button type="button" onClick={() => removeCell(cell.cellId)} className="rounded-lg border border-red-200 bg-white p-1.5 text-red-700" title="Delete"><Trash2 size={14} /></button>
                      </div>
                    </div>
                    <div className="grid grid-cols-[76px_minmax(0,1fr)] gap-3 px-4 py-4">
                      <div className="pt-3 text-right font-mono text-sm font-semibold text-blue-700">{cellKind === "markdown" ? "Markdown" : `In [${cell.output?.executionCount ?? " "}]:`}</div>
                      {cellKind === "markdown" && isMarkdownPreview ? (
                        <div className="min-h-[160px] rounded-xl border border-slate-200 bg-slate-50 p-4">{markdownPreview(cell.source)}</div>
                      ) : (
                        <textarea ref={(element) => { cellRefs.current[cell.cellId] = element; }} value={cell.source} onChange={(event) => updateCell(cell.cellId, { source: event.target.value })} className="min-h-[180px] w-full rounded-xl border border-slate-300 bg-white p-3 font-mono text-xs leading-5 text-slate-900" />
                      )}
                      <div className="pt-3 text-right font-mono text-sm font-semibold text-emerald-700">{executionLabel}</div>
                      <NotebookOutputRenderer output={cell.output} cellType={displayCellType} executionLabel={executionLabel} />
                    </div>
                    <div className="border-t border-slate-100 px-4 py-2 text-right text-xs text-slate-400">Cell {index + 1} of {notebook?.cells.length || 0}</div>
                  </article>
                  <div className="relative my-2 flex justify-center">
                    <button type="button" onClick={() => setOpenInsertAfterCellId(openInsertAfterCellId === cell.cellId ? null : cell.cellId)} className="rounded-full border border-slate-300 bg-white px-3 py-1 text-xs font-semibold text-slate-600 shadow-sm hover:border-blue-300 hover:text-blue-700">
                      + Add Cell
                    </button>
                    {openInsertAfterCellId === cell.cellId && (
                      <div className="absolute top-8 z-20 w-56 rounded-xl border border-slate-200 bg-white p-2 shadow-lg">
                        <button type="button" onClick={() => addCellBelow(cell.cellId, "markdown")} className="block w-full rounded-lg px-3 py-2 text-left text-xs font-semibold text-slate-700 hover:bg-blue-50">
                          Markdown
                        </button>
                        <button type="button" onClick={() => addCellBelow(cell.cellId, "code")} className="block w-full rounded-lg px-3 py-2 text-left text-xs font-semibold text-slate-700 hover:bg-blue-50">
                          Code ({codeLanguageLabel(defaultCodeLanguage)})
                        </button>
                        <div className="my-1 border-t border-slate-100" />
                        <div className="max-h-52 overflow-auto">
                          {visibleTemplates.slice(0, 12).map((template) => (
                            <button key={`insert-${template.group}-${template.label}`} type="button" onClick={() => addCellBelow(cell.cellId, template.cellType === "markdown" ? "markdown" : "code", template.source, template.cellType === "markdown" ? defaultCodeLanguage : template.cellType as NotebookCodeLanguage)} className="block w-full rounded-lg px-3 py-2 text-left text-xs text-slate-600 hover:bg-slate-50">
                              From Template: {template.label}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                  </div>
                );
              })}
              {!notebook?.cells?.length && <div className="rounded-2xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">Add a Markdown or Code cell to begin. Code cells use the selected default language.</div>}
            </div>
          </section>
        </main>

        <aside className="space-y-4">
          <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2">
              <ShieldCheck size={16} className="text-emerald-700" />
              <h2 className="text-sm font-semibold text-slate-950">Governance Controls</h2>
            </div>
            <div className="mt-3 space-y-2 text-xs leading-5 text-slate-600">
              <p className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-amber-800">Local development execution only. Do not expose notebook execution in hosted multi-user mode without sandboxing, auth, resource limits, and secrets isolation.</p>
              <p className="rounded-xl border border-blue-200 bg-blue-50 p-3 text-blue-800">Preview/sample rows only unless the backend explicitly enables full artifact execution. Warehouse-scale notebook execution is deferred.</p>
              <p className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-emerald-800">No SAS license required for SAS-compatible notebook cells. ATLAS translates supported procedures to local execution.</p>
            </div>
            <button type="button" onClick={attachEvidence} className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-emerald-700 px-3 py-2 text-sm font-semibold text-white hover:bg-emerald-800">
              <Paperclip size={15} /> Attach Notebook Output to Documentation
            </button>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2">
              <Code2 size={16} className="text-blue-700" />
              <h2 className="text-sm font-semibold text-slate-950">Add Cell From Template</h2>
            </div>
            <div className="mt-2 rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
              <div className="font-semibold text-slate-800">Cell Templates</div>
              <div>Markdown templates plus Code templates for selected language: {codeLanguageLabel(defaultCodeLanguage)}.</div>
              <label className="mt-2 inline-flex items-center gap-2 text-xs font-semibold text-slate-700">
                <input type="checkbox" checked={showAllTemplateLanguages} onChange={(event) => setShowAllTemplateLanguages(event.target.checked)} />
                Advanced: Show all languages
              </label>
            </div>
            <div className="mt-3 max-h-[340px] space-y-2 overflow-auto">
              {visibleTemplates.map((template) => (
                <button key={`${template.group}-${template.label}`} type="button" onClick={() => addTemplateCell(template)} className="w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-left hover:bg-blue-50">
                  <span className="block text-[10px] font-semibold uppercase tracking-wide text-blue-700">{template.group === "Markdown" ? "Markdown" : `Code - ${template.group}`}</span>
                  <span className="text-xs font-semibold text-slate-800">{template.label}</span>
                </button>
              ))}
            </div>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2">
              <ImageIcon size={16} className="text-teal-700" />
              <h2 className="text-sm font-semibold text-slate-950">Notebook Outputs</h2>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-3"><span className="block text-slate-500">Tables</span><strong>{outputGallery.tables.length}</strong></div>
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-3"><span className="block text-slate-500">Charts</span><strong>{outputGallery.charts.length}</strong></div>
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-3"><span className="block text-slate-500">Messages</span><strong>{outputGallery.messages.length}</strong></div>
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-3"><span className="block text-slate-500">Errors</span><strong>{outputGallery.errors.length}</strong></div>
            </div>
            <div className="mt-3 space-y-2">
              {[...outputGallery.charts, ...outputGallery.tables, ...outputGallery.errors].slice(0, 8).map((cell) => (
                <div key={`gallery-${cell.cellId}`} className="rounded-xl border border-slate-200 bg-white p-2 text-xs">
                  <div className="font-semibold text-slate-800">{effectiveCellKind(cell) === "markdown" ? "Markdown" : `Code: ${codeLanguageLabel(effectiveCellLanguage(cell, defaultCodeLanguage))}`} - {outputStatus(cell.output)}</div>
                  <div className="text-slate-500">{(cell.output?.images || []).length ? "Chart output" : (cell.output?.rows || []).length ? "Table output" : "Message/error output"}</div>
                </div>
              ))}
              {!outputGallery.charts.length && !outputGallery.tables.length && !outputGallery.errors.length && <p className="rounded-xl border border-dashed border-slate-300 p-3 text-xs text-slate-500">Run cells to populate Tables, Charts, Messages, and Errors.</p>}
            </div>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <h2 className="text-sm font-semibold text-slate-950">Dataset Fields</h2>
            <div className="mt-3 max-h-[260px] overflow-auto rounded-xl border border-slate-200 bg-slate-50 p-2">
              {datasetColumns.slice(0, 60).map((column) => <div key={column} className="rounded-lg px-2 py-1.5 text-xs text-slate-700 hover:bg-white">{column}</div>)}
              {!datasetColumns.length && <p className="p-3 text-xs text-slate-500">Select a Dataset Library asset to see fields.</p>}
            </div>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <h2 className="text-sm font-semibold text-slate-950">Exports</h2>
            <div className="mt-3 grid gap-2">
              <button type="button" onClick={exportIpynb} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">Export Jupyter .ipynb</button>
              <button type="button" onClick={exportHtml} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">Export HTML Report</button>
              <Link to="/model-document-studio" className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-center text-sm font-semibold text-slate-700 hover:bg-slate-50">Open Model Documentation Studio</Link>
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}
