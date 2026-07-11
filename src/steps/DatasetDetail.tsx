import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Database, Link2, Network, RefreshCw, ShieldCheck, Trash2 } from "lucide-react";
import BrandLogo from "../components/BrandLogo";
import {
  getDataset,
  getDatasetAccess,
  getDatasetPreview,
  getDatasetProfile,
  getUsers,
  grantDatasetAccess,
  linkDatasetToProject,
  revokeDatasetAccess,
  type AtlasUser,
  type DatasetAccessEntry,
  type DatasetProfile,
  type DatasetPreview,
  type DatasetSummary,
  type DatasetVersionSummary,
  archiveDataset,
} from "../lib/datasetLibrary";
import { isScoredOutputDataset } from "../lib/modelDiagnostics";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { listAnalyticsInsights, type AtlasAnalyticsInsight } from "../lib/analyticsWorkbench";
import { createEvidence, getDatasetEvidence, type EvidenceItem } from "../lib/evidenceGraph";

export default function DatasetDetail() {
  const { datasetId = "" } = useParams();
  const navigate = useNavigate();
  const projectId = useWorkflowStore((state) => state.projectId);
  const [dataset, setDataset] = useState<(DatasetSummary & { versions?: DatasetVersionSummary[] }) | null>(null);
  const [selectedVersion, setSelectedVersion] = useState("");
  const [profile, setProfile] = useState<DatasetProfile | null>(null);
  const [preview, setPreview] = useState<DatasetPreview | null>(null);
  const [access, setAccess] = useState<DatasetAccessEntry[]>([]);
  const [users, setUsers] = useState<AtlasUser[]>([]);
  const [shareUserId, setShareUserId] = useState("");
  const [shareRole, setShareRole] = useState("viewer");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [insights, setInsights] = useState<AtlasAnalyticsInsight[]>([]);
  const [evidenceItems, setEvidenceItems] = useState<EvidenceItem[]>([]);

  async function refresh(versionOverride?: string) {
    if (!datasetId) return;
    setLoading(true);
    setMessage("");
    try {
      const loaded = await getDataset(datasetId);
      const version = versionOverride || selectedVersion || loaded.versions?.[loaded.versions.length - 1]?.versionId || "";
      setDataset(loaded);
      setAccess((await getDatasetAccess(datasetId)).access);
      setUsers((await getUsers()).users);
      setInsights((await listAnalyticsInsights({ datasetId })).insights);
      setEvidenceItems(await getDatasetEvidence(datasetId).catch(() => []));
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

  async function shareDataset() {
    if (!datasetId || !shareUserId) return;
    try {
      await grantDatasetAccess(datasetId, shareUserId, shareRole);
      setMessage("Dataset access granted.");
      setAccess((await getDatasetAccess(datasetId)).access);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not grant dataset access.");
    }
  }

  async function revokeAccess(userId: string) {
    if (!datasetId) return;
    try {
      await revokeDatasetAccess(datasetId, userId);
      setMessage("Dataset access revoked.");
      setAccess((await getDatasetAccess(datasetId)).access);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not revoke dataset access.");
    }
  }

  async function deleteDataset() {
    if (!datasetId || !dataset) return;
    const confirmed = window.confirm(`Delete "${dataset.name}" from the Dataset Library? ATLAS will archive the dataset record so it no longer appears in the default library view.`);
    if (!confirmed) return;
    try {
      await archiveDataset(datasetId);
      setMessage("Dataset archived.");
      navigate("/datasets");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not delete this dataset.");
    }
  }

  async function saveDatasetAsEvidence() {
    if (!dataset) return;
    try {
      const saved = await createEvidence({
        projectId,
        projectName: useWorkflowStore.getState().projectName,
        evidenceType: "dataset",
        title: `Dataset: ${dataset.name}`,
        summary: dataset.description || "Governed dataset reviewed in ATLAS Dataset Library.",
        sourcePage: "Dataset Detail",
        sourceRoute: `/datasets/${dataset.datasetId}`,
        artifactType: "dataset",
        artifactId: dataset.datasetId,
        datasetIds: [dataset.datasetId],
        supportsSections: ["Data Sources", "Data Quality", "Population Definition"],
        tags: ["model_risk", dataset.domain || ""].filter(Boolean),
        status: "ready",
        importance: "high",
        lineage: { selectedVersion, sourceType: dataset.sourceType },
        governance: { note: "Raw dataset is referenced by ID; Model Evidence Center stores metadata only." },
      });
      setEvidenceItems((current) => [saved, ...current.filter((item) => item.evidenceId !== saved.evidenceId)]);
      setMessage("Dataset evidence saved to Model Evidence Center.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not save dataset evidence.");
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
            {dataset && isScoredOutputDataset(dataset) && (
              <Link to={`/model-diagnostics?datasetId=${dataset.datasetId}&versionId=${selectedVersion}`} className="inline-flex items-center gap-2 rounded-lg bg-emerald-700 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-emerald-800">
                Open Model Diagnostics
              </Link>
            )}
            {dataset && selectedVersion && (
              <Link to={`/notebook-studio?datasetId=${dataset.datasetId}&versionId=${selectedVersion}`} className="inline-flex items-center gap-2 rounded-lg bg-blue-700 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-800">
                Open Notebook Studio
              </Link>
            )}
            <Link to={`/model-evidence-center?datasetId=${datasetId}`} className="inline-flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-semibold text-blue-800 shadow-sm hover:bg-blue-100">
              <Network size={16} />
              Open Model Evidence Center
            </Link>
            <button type="button" onClick={saveDatasetAsEvidence} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50">
              Save Dataset to Model Evidence Center
            </button>
            <button type="button" onClick={() => refresh()} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50">
              <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
              Refresh
            </button>
            <button type="button" onClick={deleteDataset} className="inline-flex items-center gap-2 rounded-lg border border-red-200 bg-white px-3 py-2 text-sm font-semibold text-red-700 shadow-sm hover:bg-red-50">
              <Trash2 size={16} />
              Delete Dataset
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

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Network size={18} className="text-blue-700" />
              <h2 className="text-base font-semibold text-slate-950">Evidence linked to this dataset</h2>
            </div>
            <p className="mt-1 text-sm leading-6 text-slate-600">
              Model Evidence Center references connected SQL results, EDA, diagnostics, notebooks, charts, and governance documentation for this dataset.
            </p>
          </div>
          <Link to={`/model-evidence-center?datasetId=${datasetId}`} className="atlas-secondary-button">Open Model Evidence Center</Link>
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          {evidenceItems.length ? (
            evidenceItems.slice(0, 6).map((item) => (
              <article key={item.evidenceId} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-slate-950">{item.title}</div>
                    <div className="mt-1 text-xs text-slate-500">{item.evidenceType} · {item.sourcePage || "Model Evidence Center"}</div>
                  </div>
                  <span className="rounded-full bg-white px-2 py-1 text-[11px] font-semibold text-slate-600">{item.status}</span>
                </div>
                <p className="mt-2 line-clamp-2 text-xs leading-5 text-slate-600">{item.summary}</p>
              </article>
            ))
          ) : (
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-500">
              No Model Evidence Center items are linked to this dataset yet.
            </div>
          )}
        </div>
      </section>

      {dataset && isScoredOutputDataset(dataset) && (
        <section className="rounded-xl border border-emerald-200 bg-emerald-50 p-5 shadow-sm">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
            <div>
              <h2 className="text-base font-semibold text-emerald-950">Scored Output Dataset</h2>
              <p className="mt-1 text-sm leading-6 text-emerald-900">
                This dataset is registered as model scored output. ATLAS can run lift, calibration, residual, actual-vs-predicted, and segment diagnostics from its governed scored rows.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Link to={`/model-diagnostics?datasetId=${dataset.datasetId}&versionId=${selectedVersion}`} className="inline-flex rounded-lg bg-emerald-700 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-emerald-800">
                Open Model Diagnostics
              </Link>
              <button
                type="button"
                onClick={() => setMessage("ATLAS cannot rebuild this scored dataset because the original scoring input rows are not available. Re-run scoring and register the full scored output.")}
                className="inline-flex rounded-lg border border-emerald-300 bg-white px-3 py-2 text-sm font-semibold text-emerald-900 shadow-sm hover:bg-emerald-100"
              >
                Re-register Full Scored Dataset
              </button>
            </div>
          </div>
          <ScoredOutputCompletenessPanel dataset={dataset as DatasetSummary & { sourceInfo?: Record<string, unknown> }} profile={profile} preview={preview} />
        </section>
      )}

      {dataset && isSqlResultDataset(dataset) && (
        <section className="rounded-xl border border-indigo-200 bg-indigo-50 p-5 shadow-sm">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
            <div>
              <h2 className="text-base font-semibold text-indigo-950">SQL Data Studio Lineage</h2>
              <p className="mt-1 max-w-3xl text-sm leading-6 text-indigo-900">
                This dataset was registered from a governed SQL Data Studio query. ATLAS preserves the source query,
                upstream dataset aliases, and registration context so the result can be reused in Analytics Workbench,
                Chart Studio, modeling, or documentation.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Link to={`/sql-data-studio?datasetId=${dataset.datasetId}`} className="inline-flex rounded-lg bg-indigo-700 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-800">
                Open SQL Data Studio
              </Link>
              <Link to={`/analytics?datasetId=${dataset.datasetId}`} className="inline-flex rounded-lg border border-indigo-300 bg-white px-3 py-2 text-sm font-semibold text-indigo-900 shadow-sm hover:bg-indigo-100">
                Open Analytics
              </Link>
              <Link to={`/chart-studio?datasetId=${dataset.datasetId}`} className="inline-flex rounded-lg border border-indigo-300 bg-white px-3 py-2 text-sm font-semibold text-indigo-900 shadow-sm hover:bg-indigo-100">
                Open Chart Studio
              </Link>
            </div>
          </div>
          <SqlLineagePanel dataset={dataset as DatasetSummary & { sourceInfo?: Record<string, unknown> }} />
        </section>
      )}

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
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-base font-semibold text-slate-950">Saved Analytics Insights and Chart Insights</h2>
            <p className="mt-1 text-sm leading-6 text-slate-600">
              Findings created in Analytics Workbench and Chart Studio for this governed dataset.
            </p>
          </div>
          <Link to="/chart-studio" className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50">
            Open Chart Studio
          </Link>
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          {insights.length ? (
            insights.slice(0, 6).map((insight) => (
              <article key={insight.insightId} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-3">
                <div className="text-sm font-semibold text-slate-950">{insight.title}</div>
                <p className="mt-1 line-clamp-3 text-xs leading-5 text-slate-600">{insight.summary || "No narrative summary was saved."}</p>
                <div className="mt-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                  {(insight.analysisType === "chart_studio" ? `Chart Studio - ${insight.evidence?.chartType || "chart"}` : insight.analysisType)} - {new Date(insight.createdAt).toLocaleString()}
                </div>
              </article>
            ))
          ) : (
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-500">
              No analytics or chart insights are saved for this dataset yet.
            </div>
          )}
        </div>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center gap-2">
          <ShieldCheck size={18} className="text-blue-700" />
          <h2 className="text-base font-semibold text-slate-950">Dataset Access</h2>
        </div>
        <p className="mt-1 text-sm leading-6 text-slate-600">
          Grant governed access to another ATLAS user. Backend permissions determine whether this action is allowed.
        </p>
        <div className="mt-4 grid gap-3 lg:grid-cols-[1fr_180px_auto]">
          <select className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm" value={shareUserId} onChange={(event) => setShareUserId(event.target.value)}>
            <option value="">Select user...</option>
            {users.map((user) => (
              <option key={user.userId} value={user.userId}>
                {user.displayName} ({user.role})
              </option>
            ))}
          </select>
          <select className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm" value={shareRole} onChange={(event) => setShareRole(event.target.value)}>
            <option value="viewer">Viewer</option>
            <option value="editor">Editor</option>
            <option value="auditor">Auditor</option>
          </select>
          <button type="button" onClick={shareDataset} className="rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800">
            Share Dataset
          </button>
        </div>
        <div className="mt-4 overflow-auto rounded-lg border border-slate-200">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2 text-left">User</th>
                <th className="px-3 py-2 text-left">Permission</th>
                <th className="px-3 py-2 text-left">Granted</th>
                <th className="px-3 py-2 text-left">Action</th>
              </tr>
            </thead>
            <tbody>
              {access.map((entry) => {
                const userId = entry.user_id ?? entry.userId ?? "";
                const found = users.find((user) => user.userId === userId);
                return (
                  <tr key={`${userId}-${entry.role}`} className="border-t">
                    <td className="px-3 py-2 font-semibold">{found?.displayName ?? userId}</td>
                    <td className="px-3 py-2">{entry.role}</td>
                    <td className="px-3 py-2">{entry.granted_at ? new Date(entry.granted_at).toLocaleString() : "-"}</td>
                    <td className="px-3 py-2">
                      {entry.role !== "owner" && (
                        <button type="button" onClick={() => revokeAccess(userId)} className="rounded border border-red-200 px-2 py-1 text-xs font-semibold text-red-700 hover:bg-red-50">
                          Revoke
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
              {!access.length && (
                <tr>
                  <td className="px-3 py-4 text-slate-500" colSpan={4}>No explicit access grants are registered.</td>
                </tr>
              )}
            </tbody>
          </table>
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

function ScoredOutputCompletenessPanel({
  dataset,
  profile,
  preview,
}: {
  dataset: DatasetSummary & { sourceInfo?: Record<string, unknown> };
  profile: DatasetProfile | null;
  preview: DatasetPreview | null;
}) {
  const sourceInfo = dataset.sourceInfo ?? {};
  const roles = (sourceInfo.columnRoles && typeof sourceInfo.columnRoles === "object" ? sourceInfo.columnRoles : {}) as Record<string, unknown>;
  const columns = preview?.columns?.length ? preview.columns : (profile?.schema ?? []).map((column) => column.name);
  const lower = new Set(columns.map((column) => column.toLowerCase()));
  const diagnosticOnly = new Set(["row", "score", "adjusted_score", "probability", "prediction", "predicted", "predicted_value", "actual", "atlas_residual", "atlas_abs_residual", "atlas_squared_residual", "atlas_percent_error", "atlas_score_decile", "split"]);
  const featureColumns = columns.filter((column) => !diagnosticOnly.has(column.toLowerCase()));
  const task = String(sourceInfo.task ?? "").toLowerCase();
  const hasPrediction = Boolean(roles.prediction || roles.score || lower.has("prediction") || lower.has("predicted_value") || lower.has("score"));
  const hasActual = Boolean(roles.actual || roles.target || lower.has("actual"));
  const hasTarget = hasActual || Boolean(sourceInfo.targetColumn && lower.has(String(sourceInfo.targetColumn).toLowerCase()));
  const hasResidual = Boolean(roles.residual || lower.has("atlas_residual")) && lower.has("atlas_abs_residual") && lower.has("atlas_squared_residual");
  const hasFeatures = featureColumns.length > 0;
  const predictionOnly = hasPrediction && !hasFeatures;
  let readiness = "Needs field mapping";
  if (task === "regression" && hasFeatures && hasPrediction && hasTarget && hasResidual) readiness = "Ready for regression diagnostics";
  else if (task === "classification" && hasFeatures && hasPrediction) readiness = "Ready for classification diagnostics";
  else if (predictionOnly && !hasTarget) readiness = "Prediction-only, actual target missing";
  else if (predictionOnly) readiness = "Prediction-only, original features missing";
  return (
    <div className="mt-5 rounded-xl border border-emerald-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-950">Scored Output Completeness</h3>
          <p className="mt-1 text-xs leading-5 text-slate-600">ATLAS checks whether this scored output can support full regression or classification diagnostics.</p>
        </div>
        <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${readiness.startsWith("Ready") ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-amber-200 bg-amber-50 text-amber-800"}`}>
          Diagnostic readiness: {readiness}
        </span>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        <CompletenessCheck label="Feature columns present" ok={hasFeatures} value={featureColumns.length ? `${featureColumns.length}` : "No"} />
        <CompletenessCheck label="Target column present" ok={hasTarget} value={hasTarget ? "Yes" : "No"} />
        <CompletenessCheck label="Prediction column present" ok={hasPrediction} value={hasPrediction ? String(roles.prediction || roles.score || "Detected") : "No"} />
        <CompletenessCheck label="Residual fields present" ok={task !== "regression" || hasResidual} value={hasResidual ? "Yes" : task === "regression" ? "No" : "N/A"} />
        <CompletenessCheck label="Rows reviewed" ok value={String(preview?.rows?.length ?? profile?.profiledRows ?? 0)} />
        <CompletenessCheck label="Columns reviewed" ok value={String(columns.length)} />
      </div>
      {predictionOnly && (
        <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-900">
          Warning: this scored output contains predictions only. Full diagnostic registration requires original feature columns and target values.
        </div>
      )}
    </div>
  );
}

function SqlLineagePanel({ dataset }: { dataset: DatasetSummary & { sourceInfo?: Record<string, unknown> } }) {
  const sourceInfo = dataset.sourceInfo ?? {};
  const sources = Array.isArray(sourceInfo.sourceDatasets) ? sourceInfo.sourceDatasets : [];
  const sqlQuery = typeof sourceInfo.sqlQuery === "string" ? sourceInfo.sqlQuery : "";
  return (
    <div className="mt-4 grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
      <div className="rounded-xl border border-indigo-200 bg-white/80 p-4">
        <h3 className="text-sm font-semibold text-indigo-950">Source Datasets</h3>
        <div className="mt-3 space-y-2">
          {sources.length ? (
            sources.map((source, index) => {
              const item = source && typeof source === "object" ? (source as Record<string, unknown>) : {};
              return (
                <div key={`${String(item.datasetId ?? index)}-${String(item.alias ?? index)}`} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs">
                  <div className="font-semibold text-slate-950">{String(item.alias ?? `source_${index + 1}`)}</div>
                  <div className="mt-1 text-slate-600">Dataset: {String(item.datasetId ?? "-")}</div>
                  <div className="text-slate-600">Version: {String(item.versionId ?? "-")}</div>
                </div>
              );
            })
          ) : (
            <div className="rounded-lg border border-dashed border-indigo-200 bg-white px-3 py-2 text-xs text-indigo-900">No source dataset lineage was attached.</div>
          )}
        </div>
      </div>
      <div className="rounded-xl border border-indigo-200 bg-white/80 p-4">
        <h3 className="text-sm font-semibold text-indigo-950">Registered Query</h3>
        <pre className="mt-3 max-h-72 overflow-auto rounded-lg bg-slate-950 p-3 text-xs leading-5 text-slate-100">{sqlQuery || "No SQL query was attached to this result dataset."}</pre>
        <div className="mt-3 grid gap-2 sm:grid-cols-3">
          <Meta label="Query Name" value={String(sourceInfo.queryName ?? dataset.name)} />
          <Meta label="Linked Project" value={String(sourceInfo.linkedProjectId ?? "-")} />
          <Meta label="Registered At" value={dataset.createdAt ? new Date(dataset.createdAt).toLocaleString() : "-"} />
        </div>
      </div>
    </div>
  );
}

function isSqlResultDataset(dataset: DatasetSummary) {
  return (
    dataset.datasetRole === "sql_result" ||
    dataset.sourceType === "sql_studio" ||
    dataset.sourceInfo?.sourceType === "sql_studio" ||
    dataset.sourceInfo?.datasetRole === "sql_result"
  );
}

function CompletenessCheck({ label, ok, value }: { label: string; ok: boolean; value: string }) {
  return (
    <div className={`rounded-lg border px-3 py-2 ${ok ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-amber-200 bg-amber-50 text-amber-900"}`}>
      <div className="text-[10px] font-semibold uppercase tracking-wide">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold" title={value}>{value}</div>
    </div>
  );
}
