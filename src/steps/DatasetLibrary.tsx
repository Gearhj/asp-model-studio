import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Database, FilePlus2, RefreshCw, Search, ShieldCheck, UploadCloud } from "lucide-react";
import BrandLogo from "../components/BrandLogo";
import {
  listDatasets,
  uploadDataset,
  type AtlasUser,
  type DatasetSummary,
} from "../lib/datasetLibrary";

export default function DatasetLibrary() {
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [currentUser, setCurrentUser] = useState<AtlasUser | null>(null);
  const [query, setQuery] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return datasets;
    return datasets.filter((dataset) =>
      [dataset.name, dataset.description, dataset.domain, dataset.sourceType, dataset.ownerDisplayName]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(needle)
    );
  }, [datasets, query]);

  async function refresh() {
    setLoading(true);
    setMessage("");
    try {
      const payload = await listDatasets();
      setDatasets(payload.datasets);
      setCurrentUser(payload.currentUser);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not load the dataset library.");
    } finally {
      setLoading(false);
    }
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
                Viewing as {currentUser.displayName} ({currentUser.role})
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
        <label className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
          <Search size={16} className="text-slate-500" />
          <input
            className="w-full bg-transparent text-sm outline-none"
            placeholder="Search datasets by name, domain, source, or owner"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
      </section>

      <section className="grid gap-4 xl:grid-cols-3">
        {filtered.map((dataset) => (
          <Link key={dataset.datasetId} to={`/datasets/${dataset.datasetId}`} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition hover:-translate-y-0.5 hover:border-blue-200 hover:shadow-md">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h2 className="truncate text-base font-semibold text-slate-950">{dataset.name}</h2>
                <p className="mt-1 line-clamp-2 text-sm leading-5 text-slate-600">{dataset.description || "No description provided."}</p>
              </div>
              <span className="rounded-full bg-slate-100 px-2 py-1 text-[11px] font-semibold uppercase text-slate-600">{dataset.sourceType || "dataset"}</span>
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
            </div>
          </Link>
        ))}
      </section>

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

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-2 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold text-slate-950">{value}</div>
    </div>
  );
}

