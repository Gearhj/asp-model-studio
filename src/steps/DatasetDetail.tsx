import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Database, Link2, RefreshCw, ShieldCheck } from "lucide-react";
import BrandLogo from "../components/BrandLogo";
import {
  getDataset,
  getDatasetPreview,
  getDatasetProfile,
  linkDatasetToProject,
  type DatasetProfile,
  type DatasetPreview,
  type DatasetSummary,
  type DatasetVersionSummary,
} from "../lib/datasetLibrary";
import { useWorkflowStore } from "../state/useWorkflowStore";

export default function DatasetDetail() {
  const { datasetId = "" } = useParams();
  const projectId = useWorkflowStore((state) => state.projectId);
  const [dataset, setDataset] = useState<(DatasetSummary & { versions?: DatasetVersionSummary[] }) | null>(null);
  const [selectedVersion, setSelectedVersion] = useState("");
  const [profile, setProfile] = useState<DatasetProfile | null>(null);
  const [preview, setPreview] = useState<DatasetPreview | null>(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  async function refresh(versionOverride?: string) {
    if (!datasetId) return;
    setLoading(true);
    setMessage("");
    try {
      const loaded = await getDataset(datasetId);
      const version = versionOverride || selectedVersion || loaded.versions?.[loaded.versions.length - 1]?.versionId || "";
      setDataset(loaded);
      setSelectedVersion(version);
      if (version) {
        const profilePayload = await getDatasetProfile(datasetId, version);
        setProfile(profilePayload.profile);
        setPreview(await getDatasetPreview(datasetId, version));
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not load this dataset.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, [datasetId]);

  async function linkToProject() {
    if (!datasetId || !selectedVersion) return;
    try {
      await linkDatasetToProject(projectId, datasetId, selectedVersion, "modeling");
      setMessage("Dataset version linked to the current project.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not link this dataset to the project.");
    }
  }

  return (
    <div className="w-full space-y-5">
      <section className="rounded-xl border border-slate-200/80 bg-white/90 p-5 shadow-sm">
        <BrandLogo size="md" variant="light" showSubtitle className="mb-3" />
        <Link to="/datasets" className="inline-flex items-center gap-2 text-sm font-semibold text-blue-700 hover:text-blue-900">
          <ArrowLeft size={15} />
          Dataset Library
        </Link>
        <div className="mt-3 flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Database size={21} className="text-blue-700" />
              <h1 className="text-xl font-semibold text-slate-950">{dataset?.name || "Dataset Detail"}</h1>
            </div>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">{dataset?.description || "Governed dataset metadata, profile, lineage, access, and preview."}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <select
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
              value={selectedVersion}
              onChange={(event) => {
                setSelectedVersion(event.target.value);
                refresh(event.target.value);
              }}
            >
              {(dataset?.versions ?? []).map((version) => (
                <option key={version.versionId} value={version.versionId}>
                  {version.versionId}
                </option>
              ))}
            </select>
            <button type="button" onClick={linkToProject} className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800">
              <Link2 size={16} />
              Link to Current Project
            </button>
            <button type="button" onClick={() => refresh()} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50">
              <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
              Refresh
            </button>
          </div>
        </div>
        {message && <div className="mt-4 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-900">{message}</div>}
      </section>

      <section className="grid gap-4 md:grid-cols-4">
        <Stat label="Rows" value={profile?.rowCount?.toLocaleString() ?? dataset?.latestVersion?.rowCount?.toLocaleString() ?? "-"} />
        <Stat label="Columns" value={profile?.columnCount?.toLocaleString() ?? dataset?.latestVersion?.columnCount?.toLocaleString() ?? "-"} />
        <Stat label="Profiled Rows" value={profile?.profiledRows?.toLocaleString() ?? "-"} />
        <Stat label="Version Count" value={String(dataset?.versions?.length ?? dataset?.versionCount ?? 0)} />
      </section>

      <section className="grid gap-5 xl:grid-cols-[0.9fr_1.1fr]">
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center gap-2">
            <ShieldCheck size={18} className="text-emerald-700" />
            <h2 className="text-base font-semibold text-slate-950">Governance Metadata</h2>
          </div>
          <div className="mt-4 grid gap-3">
            <Meta label="Dataset ID" value={dataset?.datasetId} />
            <Meta label="Owner" value={dataset?.ownerDisplayName || dataset?.ownerUserId} />
            <Meta label="Domain" value={dataset?.domain} />
            <Meta label="Source Type" value={dataset?.sourceType} />
            <Meta label="Created" value={dataset?.createdAt ? new Date(dataset.createdAt).toLocaleString() : "-"} />
            <Meta label="Updated" value={dataset?.updatedAt ? new Date(dataset.updatedAt).toLocaleString() : "-"} />
          </div>
          {!!profile?.warnings?.length && (
            <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
              <div className="font-semibold">Profile Warnings</div>
              <ul className="mt-1 list-disc pl-5">
                {profile.warnings.slice(0, 6).map((warning) => <li key={warning}>{warning}</li>)}
              </ul>
            </div>
          )}
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-base font-semibold text-slate-950">Schema Profile</h2>
          <div className="mt-4 max-h-[420px] overflow-auto rounded-lg border border-slate-200">
            <table className="min-w-full text-sm">
              <thead className="sticky top-0 bg-slate-50 text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-3 py-2 text-left">Column</th>
                  <th className="px-3 py-2 text-left">Type</th>
                  <th className="px-3 py-2 text-right">Missing %</th>
                  <th className="px-3 py-2 text-right">Distinct</th>
                  <th className="px-3 py-2 text-right">Mean</th>
                </tr>
              </thead>
              <tbody>
                {(profile?.schema ?? []).map((column) => (
                  <tr key={column.name} className="border-t">
                    <td className="px-3 py-2 font-medium">{column.name}</td>
                    <td className="px-3 py-2">{column.dtype}</td>
                    <td className="px-3 py-2 text-right">{((column.missingPctSample ?? 0) * 100).toFixed(2)}%</td>
                    <td className="px-3 py-2 text-right">{column.distinctSample?.toLocaleString?.() ?? "-"}</td>
                    <td className="px-3 py-2 text-right">{column.mean == null ? "-" : column.mean.toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-base font-semibold text-slate-950">Preview</h2>
        <div className="mt-4 max-h-[440px] overflow-auto rounded-lg border border-slate-200">
          <table className="min-w-full text-xs">
            <thead className="sticky top-0 bg-slate-50 text-slate-500">
              <tr>{(preview?.columns ?? []).map((column) => <th key={column} className="whitespace-nowrap px-3 py-2 text-left">{column}</th>)}</tr>
            </thead>
            <tbody>
              {(preview?.rows ?? []).map((row, index) => (
                <tr key={index} className="border-t">
                  {(preview?.columns ?? []).map((column) => <td key={column} className="whitespace-nowrap px-3 py-2">{String(row[column] ?? "")}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
          {!preview?.rows?.length && <div className="p-8 text-center text-sm text-slate-500">No preview rows are available for this version.</div>}
        </div>
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200/80 bg-white/90 p-4 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-2 truncate text-xl font-semibold text-slate-950" title={value}>{value}</div>
    </div>
  );
}

function Meta({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 break-all text-sm font-semibold text-slate-950">{value || "-"}</div>
    </div>
  );
}

