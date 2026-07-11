import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { BarChart3, Database, Download, FilePlus2, LineChart, RefreshCw, Search, ShieldCheck, Table2, Trash2, UploadCloud } from "lucide-react";
import BrandLogo from "../components/BrandLogo";
import {
  archiveDataset,
  linkDatasetToProject,
  listDatasets,
  uploadDataset,
  type AtlasUser,
  type DatasetSummary,
} from "../lib/datasetLibrary";
import { isScoredOutputDataset } from "../lib/modelDiagnostics";
import { useWorkflowStore } from "../state/useWorkflowStore";

const DATASET_LIBRARY_VIEW_MODE_KEY = "atlas-dataset-library-view-mode";

type ViewMode = "card" | "detail";
type DatasetSortKey = "name" | "type" | "rows" | "columns" | "updated" | "created" | "owner" | "status";
type SortDirection = "asc" | "desc";

function readSavedViewMode(key: string, fallback: ViewMode = "detail"): ViewMode {
  if (typeof localStorage === "undefined") return fallback;
  const saved = localStorage.getItem(key);
  return saved === "card" || saved === "detail" ? saved : fallback;
}

export default function DatasetLibrary() {
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [currentUser, setCurrentUser] = useState<AtlasUser | null>(null);
  const [query, setQuery] = useState("");
  const [datasetFilter, setDatasetFilter] = useState("all");
  const [ownerFilter, setOwnerFilter] = useState("all");
  const [viewMode, setViewMode] = useState<ViewMode>(() => readSavedViewMode(DATASET_LIBRARY_VIEW_MODE_KEY, "detail"));
  const [sort, setSort] = useState<{ key: DatasetSortKey; direction: SortDirection }>({ key: "updated", direction: "desc" });
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const currentProjectId = useWorkflowStore((state) => state.projectId);

  const ownerOptions = useMemo(() => {
    const owners = new Map<string, string>();
    datasets.forEach((dataset) => {
      const key = dataset.ownerUserId || dataset.ownerDisplayName || "unknown";
      const label = dataset.ownerDisplayName || dataset.ownerUserId || "Unknown";
      owners.set(key, label);
    });
    return Array.from(owners.entries()).sort((a, b) => a[1].localeCompare(b[1]));
  }, [datasets]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const filteredDatasets = datasets.filter((dataset) => {
      const text = [
        dataset.name,
        dataset.description,
        dataset.domain,
        dataset.sourceType,
        dataset.ownerDisplayName,
        dataset.ownerUserId,
        dataset.datasetRole,
        dataset.sourceInfo?.task,
        dataset.sourceInfo?.datasetType,
        dataset.latestVersion?.versionId,
        dataset.linkedProjects?.map((link) => `${link.projectId} ${link.datasetRole}`).join(" "),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
      const matchesSearch = !needle || text.includes(needle);
      const ownerKey = dataset.ownerUserId || dataset.ownerDisplayName || "unknown";
      const roleText = `${dataset.name} ${dataset.datasetRole ?? ""} ${dataset.sourceInfo?.datasetType ?? ""}`.toLowerCase();
      const taskText = `${dataset.name} ${dataset.sourceInfo?.task ?? ""}`.toLowerCase();
      const matchesFilter =
        datasetFilter === "all" ||
        (datasetFilter === "training" && /train|training/.test(roleText)) ||
        (datasetFilter === "test" && /\btest\b/.test(roleText)) ||
        (datasetFilter === "oot" && /oot|out-of-time/.test(roleText)) ||
        (datasetFilter === "scored" && isScoredOutputDataset(dataset)) ||
        (datasetFilter === "sql-result" && isSqlResultDataset(dataset)) ||
        (datasetFilter === "regression" && /regression|reg_/.test(taskText)) ||
        (datasetFilter === "classification" && /classification|class_|fraud/.test(taskText)) ||
        (datasetFilter === "uploaded" && dataset.sourceType === "upload") ||
        (datasetFilter === "metadata" && dataset.sourceType === "registered") ||
        (datasetFilter === "linked-current" && Boolean(dataset.linkedProjects?.some((link) => link.projectId === currentProjectId))) ||
        (datasetFilter === "unlinked" && !(dataset.linkedProjects?.length));
      const matchesOwner = ownerFilter === "all" || ownerFilter === ownerKey;
      return matchesSearch && matchesFilter && matchesOwner;
    });
    return [...filteredDatasets].sort((a, b) => {
      const comparison = compareDatasetRows(a, b, sort.key);
      return sort.direction === "asc" ? comparison : -comparison;
    });
  }, [currentProjectId, datasetFilter, datasets, ownerFilter, query, sort]);

  const setDatasetViewMode = (mode: ViewMode) => {
    setViewMode(mode);
    if (typeof localStorage !== "undefined") localStorage.setItem(DATASET_LIBRARY_VIEW_MODE_KEY, mode);
  };

  const toggleDatasetSort = (key: DatasetSortKey) => {
    setSort((current) => ({
      key,
      direction: current.key === key && current.direction === "asc" ? "desc" : "asc",
    }));
  };

  async function refresh() {
    setLoading(true);
    setMessage("");
    try {
      const payload = await listDatasets();
      setDatasets(payload.datasets);
      setCurrentUser(payload.currentUser);
      setViewMode((current) => (payload.datasets.length > 9 ? "detail" : current));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not load the dataset library.");
    } finally {
      setLoading(false);
    }
  }

  async function deleteDataset(dataset: DatasetSummary) {
    const confirmed = window.confirm(`Delete "${dataset.name}" from the Dataset Library? ATLAS will archive the record so governance history remains intact.`);
    if (!confirmed) return;
    setMessage(`Deleting ${dataset.name}...`);
    try {
      await archiveDataset(dataset.datasetId);
      setMessage(`Deleted "${dataset.name}" from active Dataset Library views.`);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not delete this dataset.");
    }
  }

  async function linkToCurrentProject(dataset: DatasetSummary) {
    const versionId = dataset.latestVersion?.versionId;
    if (!versionId) {
      setMessage("This dataset has no version to link.");
      return;
    }
    try {
      await linkDatasetToProject(currentProjectId, dataset.datasetId, versionId, dataset.datasetRole || "modeling");
      setMessage(`Linked "${dataset.name}" to the current project.`);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not link this dataset to the current project.");
    }
  }

  function exportMetadata(dataset: DatasetSummary) {
    const blob = new Blob([JSON.stringify(dataset, null, 2)], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${dataset.name.replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "").toLowerCase() || "atlas-dataset"}-metadata.json`;
    anchor.click();
    URL.revokeObjectURL(url);
    setMessage(`Exported metadata for "${dataset.name}".`);
  }

  useEffect(() => {
    refresh();
  }, []);

  async function onUpload(file: File) {
    setUploading(true);
    setMessage(`Registering ${file.name} in the ATLAS Dataset Library...`);
    try {
      const dataset = await uploadDataset({ file, name: file.name.replace(/\.[^.]+$/, ""), sourceType: "upload" });
      setMessage(`Registered ${dataset.name} with ${dataset.latestVersion?.rowCount?.toLocaleString() ?? "profiled"} rows.`);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not register this dataset.");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="w-full space-y-5">
      <section className="rounded-xl border border-slate-200/80 bg-white/90 p-5 shadow-sm">
        <BrandLogo size="md" variant="light" showSubtitle className="mb-3" />
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Database size={21} className="text-blue-700" />
              <h1 className="text-xl font-semibold text-slate-950">Dataset Library</h1>
            </div>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">
              Register governed datasets once, preserve versions and lineage, then link approved data assets to ATLAS projects.
            </p>
            {currentUser && (
              <p className="mt-2 inline-flex items-center gap-2 rounded-full bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-800">
                <ShieldCheck size={13} />
                Signed in as {currentUser.displayName} ({currentUser.role})
              </p>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800">
              <UploadCloud size={16} />
              Upload Dataset
              <input className="hidden" type="file" accept=".csv,.txt" onChange={(event) => event.target.files?.[0] && onUpload(event.target.files[0])} />
            </label>
            <Link to="/datasets/register" className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50">
              <FilePlus2 size={16} />
              Register Metadata
            </Link>
            <button type="button" onClick={refresh} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50">
              <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
              Refresh
            </button>
          </div>
        </div>
        {message && (
          <div className={`mt-4 rounded-lg border px-3 py-2 text-sm ${message.includes("could not") || message.includes("failed") ? "border-red-200 bg-red-50 text-red-900" : "border-blue-200 bg-blue-50 text-blue-900"}`}>
            {message}
          </div>
        )}
      </section>

      <section className="rounded-xl border border-slate-200/80 bg-white/90 p-4 shadow-sm">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <label className="flex min-w-[320px] flex-1 items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
            <Search size={16} className="text-slate-500" />
            <input
              className="w-full bg-transparent text-sm outline-none"
              placeholder="Search by dataset, owner, source, linked project, or type"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={datasetFilter}
              onChange={(event) => setDatasetFilter(event.target.value)}
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm"
            >
              <option value="all">All</option>
              <option value="training">Training</option>
              <option value="test">Test</option>
              <option value="oot">OOT</option>
              <option value="scored">Scored Outputs</option>
              <option value="sql-result">SQL Results</option>
              <option value="regression">Regression</option>
              <option value="classification">Classification</option>
              <option value="uploaded">Uploaded</option>
              <option value="metadata">Metadata-only</option>
              <option value="linked-current">Linked to Current Project</option>
              <option value="unlinked">Unlinked</option>
            </select>
            <select
              value={ownerFilter}
              onChange={(event) => setOwnerFilter(event.target.value)}
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm"
            >
              <option value="all">All Owners</option>
              {ownerOptions.map(([ownerKey, ownerLabel]) => (
                <option key={ownerKey} value={ownerKey}>{ownerLabel}</option>
              ))}
            </select>
            <div className="inline-flex rounded-lg border border-slate-300 bg-white p-1 shadow-sm">
              <button type="button" onClick={() => setDatasetViewMode("card")} className={`rounded-md px-2 py-1.5 text-xs font-semibold ${viewMode === "card" ? "bg-slate-950 text-white" : "text-slate-600 hover:bg-slate-50"}`}>
                Card View
              </button>
              <button type="button" onClick={() => setDatasetViewMode("detail")} className={`inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-xs font-semibold ${viewMode === "detail" ? "bg-slate-950 text-white" : "text-slate-600 hover:bg-slate-50"}`}>
                <Table2 size={13} />
                Detailed View
              </button>
            </div>
          </div>
        </div>
      </section>

      {viewMode === "detail" ? (
        <DatasetDetailTable datasets={filtered} sort={sort} onSort={toggleDatasetSort} onDelete={deleteDataset} onExportMetadata={exportMetadata} onLinkToProject={linkToCurrentProject} />
      ) : (
      <section className="grid gap-4 xl:grid-cols-3">
        {filtered.map((dataset) => (
          <Link key={dataset.datasetId} to={`/datasets/${dataset.datasetId}`} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition hover:-translate-y-0.5 hover:border-blue-200 hover:shadow-md">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h2 className="truncate text-base font-semibold text-slate-950">{dataset.name}</h2>
                <p className="mt-1 line-clamp-2 text-sm leading-5 text-slate-600">{dataset.description || "No description provided."}</p>
              </div>
              <span className={`rounded-full px-2 py-1 text-[11px] font-semibold uppercase ${isSqlResultDataset(dataset) ? "bg-indigo-100 text-indigo-800" : isScoredOutputDataset(dataset) ? "bg-emerald-100 text-emerald-800" : "bg-slate-100 text-slate-600"}`}>
                {isSqlResultDataset(dataset) ? "SQL Result" : isScoredOutputDataset(dataset) ? "Scored Output" : dataset.sourceType || "dataset"}
              </span>
            </div>
            <div className="mt-4 grid grid-cols-3 gap-2 text-xs">
              <Metric label="Rows" value={dataset.latestVersion?.rowCount?.toLocaleString() ?? "-"} />
              <Metric label="Columns" value={dataset.latestVersion?.columnCount?.toLocaleString() ?? "-"} />
              <Metric label="Versions" value={String(dataset.versionCount ?? 0)} />
            </div>
            <div className="mt-4 border-t border-slate-100 pt-3 text-xs leading-5 text-slate-500">
              <div>Owner: {dataset.ownerDisplayName || dataset.ownerUserId || "Unknown"}</div>
              <div>Updated: {dataset.updatedAt ? new Date(dataset.updatedAt).toLocaleString() : "Not available"}</div>
              <div className="truncate">Latest version: {dataset.latestVersion?.versionId || "No version"}</div>
              {isScoredOutputDataset(dataset) && (
                <div className="mt-2 font-semibold text-emerald-700">Ready for Model Diagnostics</div>
              )}
              {isSqlResultDataset(dataset) && (
                <div className="mt-2 font-semibold text-indigo-700">Created by SQL Data Studio</div>
              )}
            </div>
          </Link>
        ))}
      </section>
      )}

      {!loading && !filtered.length && (
        <section className="rounded-xl border border-dashed border-slate-300 bg-white/80 p-10 text-center shadow-sm">
          <Database size={40} className="mx-auto text-blue-700" />
          <h2 className="mt-3 text-lg font-semibold text-slate-950">No datasets found</h2>
          <p className="mx-auto mt-2 max-w-2xl text-sm leading-6 text-slate-600">
            Upload a CSV/TXT file to create the first governed dataset record. ATLAS will profile schema, store compact preview artifacts, and make the dataset reusable from Data Acquisition.
          </p>
        </section>
      )}

      {(loading || uploading) && <div className="text-sm font-semibold text-slate-500">Working...</div>}
    </div>
  );
}

function DatasetDetailTable({
  datasets,
  sort,
  onSort,
  onDelete,
  onExportMetadata,
  onLinkToProject,
}: {
  datasets: DatasetSummary[];
  sort: { key: DatasetSortKey; direction: SortDirection };
  onSort: (key: DatasetSortKey) => void;
  onDelete: (dataset: DatasetSummary) => void;
  onExportMetadata: (dataset: DatasetSummary) => void;
  onLinkToProject: (dataset: DatasetSummary) => void;
}) {
  return (
    <section className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
      <table className="min-w-[1320px] w-full text-left text-sm">
        <thead className="sticky top-0 z-10 bg-slate-100 text-[11px] uppercase tracking-wide text-slate-500">
          <tr>
            <SortableDatasetHeader label="Dataset Name" sortKey="name" activeSort={sort} onSort={onSort} />
            <SortableDatasetHeader label="Type" sortKey="type" activeSort={sort} onSort={onSort} />
            <SortableDatasetHeader label="Rows" sortKey="rows" activeSort={sort} onSort={onSort} />
            <SortableDatasetHeader label="Columns" sortKey="columns" activeSort={sort} onSort={onSort} />
            <th className="px-3 py-3">Versions</th>
            <SortableDatasetHeader label="Owner" sortKey="owner" activeSort={sort} onSort={onSort} />
            <SortableDatasetHeader label="Created" sortKey="created" activeSort={sort} onSort={onSort} />
            <SortableDatasetHeader label="Updated" sortKey="updated" activeSort={sort} onSort={onSort} />
            <th className="px-3 py-3">Linked Projects</th>
            <th className="px-3 py-3">Latest Version</th>
            <th className="px-3 py-3">Source Type</th>
            <SortableDatasetHeader label="Status" sortKey="status" activeSort={sort} onSort={onSort} />
            <th className="px-3 py-3">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {datasets.map((dataset) => (
            <tr key={dataset.datasetId} className="odd:bg-white even:bg-slate-50/60">
              <td className="max-w-[280px] px-3 py-2">
                <div className="truncate font-semibold text-slate-950" title={dataset.name}>{dataset.name}</div>
                <div className="line-clamp-2 text-xs text-slate-500">{dataset.description || dataset.datasetId}</div>
              </td>
              <td className="px-3 py-2 capitalize text-slate-700">{formatDatasetType(dataset)}</td>
              <td className="px-3 py-2 text-slate-700">{dataset.latestVersion?.rowCount?.toLocaleString() ?? "-"}</td>
              <td className="px-3 py-2 text-slate-700">{dataset.latestVersion?.columnCount?.toLocaleString() ?? "-"}</td>
              <td className="px-3 py-2 text-slate-700">{dataset.versionCount ?? 0}</td>
              <td className="px-3 py-2 text-slate-700">{dataset.ownerDisplayName || dataset.ownerUserId || "Unknown"}</td>
              <td className="px-3 py-2 text-slate-700">{dataset.createdAt ? new Date(dataset.createdAt).toLocaleString() : "-"}</td>
              <td className="px-3 py-2 text-slate-700">{dataset.updatedAt ? new Date(dataset.updatedAt).toLocaleString() : "-"}</td>
              <td className="max-w-[220px] px-3 py-2 text-slate-700">
                {dataset.linkedProjects?.length ? (
                  <span className="rounded-full bg-blue-50 px-2 py-1 text-xs font-semibold text-blue-800" title={dataset.linkedProjects.map((link) => `${link.projectId} (${link.datasetRole})`).join(", ")}>
                    {dataset.linkedProjects.length} linked
                  </span>
                ) : "-"}
              </td>
              <td className="max-w-[180px] truncate px-3 py-2 font-mono text-xs text-slate-700" title={dataset.latestVersion?.versionId || "-"}>{dataset.latestVersion?.versionId || "-"}</td>
              <td className="px-3 py-2 capitalize text-slate-700">{formatSourceType(dataset)}</td>
              <td className="px-3 py-2">
                <span className={`rounded-full px-2 py-1 text-xs font-semibold ${dataset.archived ? "bg-slate-100 text-slate-600" : isSqlResultDataset(dataset) ? "bg-indigo-100 text-indigo-800" : isScoredOutputDataset(dataset) ? "bg-emerald-100 text-emerald-800" : "bg-blue-50 text-blue-800"}`}>
                  {dataset.archived ? "Archived" : isSqlResultDataset(dataset) ? "SQL Result" : isScoredOutputDataset(dataset) ? "Scored Output" : "Active"}
                </span>
              </td>
              <td className="px-3 py-2">
                <div className="flex flex-nowrap gap-1.5">
                  <Link to={`/datasets/${dataset.datasetId}`} className="rounded-md bg-slate-950 px-2 py-1 text-xs font-semibold text-white">Open</Link>
                  <Link to={`/analytics?datasetId=${dataset.datasetId}`} title="Open in Analytics" aria-label="Open in Analytics" className="inline-flex items-center gap-1 rounded-md border border-slate-300 bg-white px-2 py-1 text-xs font-semibold text-slate-700">
                    <Table2 size={12} />
                    Analytics
                  </Link>
                  <Link to={`/chart-studio?datasetId=${dataset.datasetId}`} title="Open in Chart Studio" aria-label="Open in Chart Studio" className="inline-flex items-center gap-1 rounded-md border border-slate-300 bg-white px-2 py-1 text-xs font-semibold text-slate-700">
                    <BarChart3 size={12} />
                    Chart
                  </Link>
                  <Link to={`/sql-data-studio?datasetId=${dataset.datasetId}`} title="Open in SQL Data Studio" aria-label="Open in SQL Data Studio" className="inline-flex items-center gap-1 rounded-md border border-indigo-200 bg-indigo-50 px-2 py-1 text-xs font-semibold text-indigo-800">
                    SQL
                  </Link>
                  {isScoredOutputDataset(dataset) && (
                    <Link to={`/model-diagnostics?datasetId=${dataset.datasetId}`} title="Open in Model Diagnostics" aria-label="Open in Model Diagnostics" className="inline-flex items-center gap-1 rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-800">
                      <LineChart size={12} />
                      Diagnostics
                    </Link>
                  )}
                  <button type="button" onClick={() => onLinkToProject(dataset)} className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs font-semibold text-slate-700">Link to Project</button>
                  <button type="button" onClick={() => onExportMetadata(dataset)} className="inline-flex items-center gap-1 rounded-md border border-slate-300 bg-white px-2 py-1 text-xs font-semibold text-slate-700">
                    <Download size={12} />
                    Export Metadata
                  </button>
                  <button type="button" onClick={() => onDelete(dataset)} className="inline-flex items-center gap-1 rounded-md border border-red-200 bg-white px-2 py-1 text-xs font-semibold text-red-700">
                    <Trash2 size={12} />
                    Delete
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function SortableDatasetHeader({
  label,
  sortKey,
  activeSort,
  onSort,
}: {
  label: string;
  sortKey: DatasetSortKey;
  activeSort: { key: DatasetSortKey; direction: SortDirection };
  onSort: (key: DatasetSortKey) => void;
}) {
  const active = activeSort.key === sortKey;
  return (
    <th className="px-3 py-3">
      <button type="button" onClick={() => onSort(sortKey)} className="inline-flex items-center gap-1 font-semibold hover:text-slate-900">
        {label}
        <span className="text-[10px]">{active ? (activeSort.direction === "asc" ? "▲" : "▼") : "↕"}</span>
      </button>
    </th>
  );
}

function formatDatasetType(dataset: DatasetSummary) {
  const text = `${dataset.datasetRole ?? ""} ${dataset.sourceInfo?.datasetType ?? ""} ${dataset.name}`.toLowerCase();
  if (isSqlResultDataset(dataset)) return "SQL Result";
  if (isScoredOutputDataset(dataset)) return "Scored Output";
  if (/train|training/.test(text)) return "Training";
  if (/\boot\b|out-of-time/.test(text)) return "OOT";
  if (/\btest\b/.test(text)) return "Test";
  if (dataset.sourceType === "upload") return "Uploaded";
  if (dataset.sourceType === "registered") return "Registered";
  if (!dataset.latestVersion) return "Metadata-only";
  return dataset.datasetRole || dataset.sourceInfo?.datasetType?.toString() || "Unknown";
}

function formatSourceType(dataset: DatasetSummary) {
  if (!dataset.latestVersion) return "Metadata-only";
  if (isSqlResultDataset(dataset)) return "SQL Data Studio";
  if (dataset.sourceType === "upload") return "Uploaded";
  if (dataset.sourceType === "registered") return "Registered";
  return dataset.sourceType || "Unknown";
}

function datasetStatus(dataset: DatasetSummary) {
  if (dataset.archived) return "Archived";
  if (isSqlResultDataset(dataset)) return "SQL Result";
  if (isScoredOutputDataset(dataset)) return "Scored Output";
  if (!dataset.latestVersion) return "Metadata-only";
  return "Active";
}

function isSqlResultDataset(dataset: DatasetSummary) {
  return (
    dataset.datasetRole === "sql_result" ||
    dataset.sourceType === "sql_studio" ||
    dataset.sourceInfo?.sourceType === "sql_studio" ||
    dataset.sourceInfo?.datasetRole === "sql_result"
  );
}

function compareDatasetRows(a: DatasetSummary, b: DatasetSummary, key: DatasetSortKey) {
  const values: Record<DatasetSortKey, [string | number, string | number]> = {
    name: [a.name, b.name],
    type: [formatDatasetType(a), formatDatasetType(b)],
    rows: [a.latestVersion?.rowCount ?? -1, b.latestVersion?.rowCount ?? -1],
    columns: [a.latestVersion?.columnCount ?? -1, b.latestVersion?.columnCount ?? -1],
    updated: [Date.parse(a.updatedAt || "") || 0, Date.parse(b.updatedAt || "") || 0],
    created: [Date.parse(a.createdAt || "") || 0, Date.parse(b.createdAt || "") || 0],
    owner: [a.ownerDisplayName || a.ownerUserId || "Unknown", b.ownerDisplayName || b.ownerUserId || "Unknown"],
    status: [datasetStatus(a), datasetStatus(b)],
  };
  const [left, right] = values[key];
  if (typeof left === "number" && typeof right === "number") return left - right;
  return String(left).localeCompare(String(right), undefined, { sensitivity: "base", numeric: true });
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-2 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold text-slate-950">{value}</div>
    </div>
  );
}
