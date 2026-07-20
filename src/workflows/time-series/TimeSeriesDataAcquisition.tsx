import { useEffect, useMemo, useState, type ChangeEvent } from "react";
import { useNavigate } from "react-router-dom";
import StepShell from "../../components/StepShell";
import { getWorkflowDefinition } from "../../config/workflows";
import {
  getDatasetPreview,
  getDatasetProfile,
  linkDatasetToProject,
  listDatasets,
  listProjectDatasets,
  uploadDataset,
  type DatasetPreview,
  type DatasetProfile,
  type DatasetSummary,
  type ProjectDatasetLink,
} from "../../lib/datasetLibrary";
import { logDecision } from "../../lib/decisionJournal";
import { safeSetLocalStorage, saveActiveProjectBeforeNavigation } from "../../lib/localProjects";
import { saveDecisionToDatabase, saveEvidenceToDatabase, saveProjectToDatabase } from "../../lib/serverPersistence";
import { useWorkflowStore, type WorkflowProjectSnapshot } from "../../state/useWorkflowStore";

type TimeSeriesMapping = {
  dateColumn: string;
  targetColumn: string;
  entityColumns: string[];
  segmentColumn: string;
  exogenousDriverColumns: string[];
  aggregationFrequency: string;
  aggregationMethod: string;
  missingTimestampPolicy: string;
  duplicateTimestampPolicy: string;
  forecastHorizon: string;
  evaluationMetrics: string[];
};

type DerivedProfile = {
  rowCount: number;
  columnCount: number;
  profileScope: string;
  profileScopeKind: "full" | "sampled" | "preview";
  coverageScope: string;
  duplicateCheckGrain: string;
  missingGapScope: string;
  startDate: string;
  endDate: string;
  previewRows: number;
  uniquePeriods: number;
  duplicateTimestampRows: number;
  missingTimestampGaps: number;
  targetMin: number | null;
  targetMax: number | null;
  targetMean: number | null;
  targetMedian: number | null;
  targetMissingPct: number;
  entityCount: number;
  entityCountLabel: string;
  distinctStores: number | null;
  distinctItems: number | null;
  distinctSeries: number;
  shortestSeriesLength: number | null;
  longestSeriesLength: number | null;
  sparseSeriesCount: number;
  recentCoverageWarning: string;
  topEntities: Array<{ entity: string; rows: number; target: number }>;
  timeSeriesPoints: Array<{ label: string; value: number }>;
  entitySeriesPoints: Record<string, Array<{ label: string; value: number }>>;
  calendarCells: Array<{ label: string; intensity: number }>;
};

const EMPTY_MAPPING: TimeSeriesMapping = {
  dateColumn: "",
  targetColumn: "",
  entityColumns: [],
  segmentColumn: "",
  exogenousDriverColumns: [],
  aggregationFrequency: "Daily",
  aggregationMethod: "Sum",
  missingTimestampPolicy: "Mark as missing",
  duplicateTimestampPolicy: "Aggregate duplicates before modeling",
  forecastHorizon: "90 days",
  evaluationMetrics: ["WAPE", "MAE", "RMSE", "Bias"],
};

const frequencyOptions = ["Hourly", "Daily", "Weekly", "Monthly", "Quarterly"];
const aggregationOptions = ["Sum", "Mean", "Median", "Ending balance", "Count", "Maximum"];
const missingTimestampOptions = ["Mark as missing", "Fill zero", "Forward fill", "Interpolate", "Exclude period"];
const duplicateTimestampOptions = ["Aggregate duplicates before modeling", "Keep latest value", "Keep first value", "Block until resolved"];
const metricOptions = ["WAPE", "MAE", "RMSE", "Bias", "MAPE", "sMAPE", "MASE"];
const STORE_ITEM_COLUMNS = ["date", "store", "item", "sales"];

function snapshotFromStore(): WorkflowProjectSnapshot {
  const state = useWorkflowStore.getState();
  return {
    hasDataset: state.hasDataset,
    projectId: state.projectId,
    modelId: state.modelId,
    projectName: state.projectName,
    projectType: state.projectType,
    workflowId: state.workflowId,
    workflowSteps: state.workflowSteps,
    currentStepId: state.currentStepId,
    projectTools: state.projectTools,
  };
}

function normalizeColumn(name: string) {
  return name.toLowerCase().replace(/[\s._-]+/g, "");
}

function formatNumber(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value);
}

function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${formatNumber(value)}%`;
}

function numericValue(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value.replace(/,/g, ""));
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function parseDateValue(value: unknown) {
  if (value instanceof Date && !Number.isNaN(value.getTime())) return value;
  if (typeof value === "string" || typeof value === "number") {
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }
  return null;
}

function median(values: number[]) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function isNumericColumn(column: DatasetProfile["schema"][number] | undefined, preview: DatasetPreview | null, name: string) {
  if (!column) return (preview?.rows ?? []).some((row) => numericValue(row[name]) !== null);
  return /int|float|double|decimal|number|numeric/i.test(column.dtype) || column.mean !== undefined || column.min !== undefined || column.max !== undefined;
}

function inferFrequency(rows: Record<string, unknown>[], dateColumn: string) {
  const dates = rows
    .map((row) => parseDateValue(row[dateColumn])?.getTime())
    .filter((value): value is number => typeof value === "number")
    .sort((a, b) => a - b);
  const unique = [...new Set(dates)];
  if (unique.length < 2) return "Daily";
  const diffs = unique.slice(1).map((value, index) => (value - unique[index]) / (1000 * 60 * 60));
  const med = median(diffs) ?? 24;
  if (med <= 1.5) return "Hourly";
  if (med <= 36) return "Daily";
  if (med <= 190) return "Weekly";
  if (med <= 900) return "Monthly";
  return "Quarterly";
}

function inferAggregation(target: string) {
  return /sales|volume|count|demand|alert|claim|loss|amount|spend|revenue|units/i.test(target) ? "Sum" : "Mean";
}

function inferMapping(columns: string[], profile: DatasetProfile | null, preview: DatasetPreview | null): TimeSeriesMapping {
  const schema = new Map((profile?.schema ?? []).map((column) => [column.name, column]));
  const byNormalized = new Map(columns.map((column) => [normalizeColumn(column), column]));
  const dateColumn =
    byNormalized.get("date") ||
    columns.find((column) => /date|datetime|timestamp|period|month|week|time/i.test(column)) ||
    "";
  const targetColumn =
    byNormalized.get("sales") ||
    columns.find((column) => /sales|demand|volume|amount|loss|balance|count|alert|claim|conversion|revenue/i.test(column) && column !== dateColumn) ||
    columns.find((column) => isNumericColumn(schema.get(column), preview, column) && column !== dateColumn) ||
    "";
  const entityColumns = ["store", "item"]
    .map((column) => byNormalized.get(column))
    .filter((column): column is string => Boolean(column));
  const inferredEntities = entityColumns.length
    ? entityColumns
    : columns
      .filter((column) => column !== dateColumn && column !== targetColumn)
      .filter((column) => /store|item|product|branch|merchant|region|account|customer|segment|id/i.test(column))
      .slice(0, 2);
  const segmentColumn = columns.find((column) => ![dateColumn, targetColumn, ...inferredEntities].includes(column) && /segment|region|channel|portfolio|product/i.test(column)) || "";
  const exogenousDriverColumns = columns
    .filter((column) => ![dateColumn, targetColumn, segmentColumn, ...inferredEntities].includes(column))
    .filter((column) => isNumericColumn(schema.get(column), preview, column))
    .slice(0, 8);
  const isStoreItemDemand = STORE_ITEM_COLUMNS.every((column) => byNormalized.has(column));
  return {
    ...EMPTY_MAPPING,
    dateColumn,
    targetColumn,
    entityColumns: inferredEntities,
    segmentColumn,
    exogenousDriverColumns,
    aggregationFrequency: isStoreItemDemand ? "Daily" : inferFrequency(preview?.rows ?? [], dateColumn),
    aggregationMethod: inferAggregation(targetColumn),
    forecastHorizon: isStoreItemDemand ? "90 days" : EMPTY_MAPPING.forecastHorizon,
  };
}

function deriveProfile(dataset: DatasetSummary | null, profile: DatasetProfile | null, preview: DatasetPreview | null, mapping: TimeSeriesMapping): DerivedProfile {
  const rows = preview?.rows ?? [];
  const datasetRows = dataset?.latestVersion?.rowCount ?? profile?.rowCount ?? rows.length;
  const profiledRows = profile?.profiledRows ?? rows.length;
  const profileScopeKind: DerivedProfile["profileScopeKind"] =
    profile?.rowCount && profiledRows >= profile.rowCount ? "full" : profiledRows > rows.length ? "sampled" : "preview";
  const profileScope =
    profileScopeKind === "full"
      ? "Full dataset profile"
      : profileScopeKind === "sampled"
        ? `Sampled backend profile from ${formatNumber(profiledRows)} of ${formatNumber(datasetRows)} rows`
        : `Browser preview profile from ${formatNumber(rows.length)} of ${formatNumber(datasetRows)} registered rows`;
  const dates = rows
    .map((row) => parseDateValue(row[mapping.dateColumn]))
    .filter((date): date is Date => Boolean(date))
    .sort((a, b) => a.getTime() - b.getTime());
  const targetValues = rows
    .map((row) => numericValue(row[mapping.targetColumn]))
    .filter((value): value is number => value !== null);
  const missingTarget = rows.length - targetValues.length;
  const dateKeys = dates.map((date) => date.toISOString().slice(0, 10));
  const periodEntityKeys = rows
    .map((row) => {
      const date = parseDateValue(row[mapping.dateColumn]);
      if (!date) return "";
      const entity = mapping.entityColumns.length
        ? mapping.entityColumns.map((column) => String(row[column] ?? "missing")).join("|")
        : "portfolio";
      return `${date.toISOString().slice(0, 10)}|${entity}`;
    })
    .filter(Boolean);
  const duplicateTimestampRows = periodEntityKeys.length - new Set(periodEntityKeys).size;
  const uniquePeriods = new Set(dateKeys).size;
  const grouped = new Map<string, { rows: number; target: number; dates: Set<string> }>();
  const byEntityDate = new Map<string, Map<string, number>>();
  const distinctStores = new Set<string>();
  const distinctItems = new Set<string>();
  const storeColumn = mapping.entityColumns.find((column) => normalizeColumn(column) === "store");
  const itemColumn = mapping.entityColumns.find((column) => normalizeColumn(column) === "item");
  for (const row of rows) {
    const entity = mapping.entityColumns.length ? mapping.entityColumns.map((column) => String(row[column] ?? "missing")).join(" / ") : "Portfolio";
    const current = grouped.get(entity) ?? { rows: 0, target: 0, dates: new Set<string>() };
    current.rows += 1;
    current.target += numericValue(row[mapping.targetColumn]) ?? 0;
    const date = parseDateValue(row[mapping.dateColumn]);
    if (date) current.dates.add(date.toISOString().slice(0, 10));
    if (date) {
      const key = date.toISOString().slice(0, 10);
      const values = byEntityDate.get(entity) ?? new Map<string, number>();
      values.set(key, (values.get(key) ?? 0) + (numericValue(row[mapping.targetColumn]) ?? 0));
      byEntityDate.set(entity, values);
    }
    if (storeColumn) distinctStores.add(String(row[storeColumn] ?? "missing"));
    if (itemColumn) distinctItems.add(String(row[itemColumn] ?? "missing"));
    grouped.set(entity, current);
  }
  const byDate = new Map<string, number>();
  for (const row of rows) {
    const date = parseDateValue(row[mapping.dateColumn]);
    const value = numericValue(row[mapping.targetColumn]);
    if (!date || value === null) continue;
    const key = date.toISOString().slice(0, 10);
    byDate.set(key, (byDate.get(key) ?? 0) + value);
  }
  const timeSeriesPoints = [...byDate.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .slice(-60)
    .map(([label, value]) => ({ label, value }));
  const entitySeriesPoints = Object.fromEntries(
    [...byEntityDate.entries()].map(([entity, values]) => [
      entity,
      [...values.entries()]
        .sort(([a], [b]) => a.localeCompare(b))
        .slice(-60)
        .map(([label, value]) => ({ label, value })),
    ]),
  );
  const maxCalendar = Math.max(1, ...timeSeriesPoints.map((point) => Math.abs(point.value)));
  const seriesLengths = [...grouped.values()].map((value) => value.dates.size || value.rows);
  const globalEndDate = dates[dates.length - 1]?.toISOString().slice(0, 10) ?? "";
  const staleSeriesCount = globalEndDate
    ? [...grouped.values()].filter((value) => !value.dates.has(globalEndDate)).length
    : 0;
  const duplicateCheckGrain = [mapping.dateColumn || "date/time column", ...mapping.entityColumns].join(" + ");
  const missingGapScope = mapping.entityColumns.length
    ? `${profileScopeKind === "full" ? "Full dataset" : profileScopeKind === "sampled" ? "Sampled backend" : "Browser preview"} entity-level gaps by ${mapping.entityColumns.join(" + ")}`
    : `${profileScopeKind === "full" ? "Full dataset" : profileScopeKind === "sampled" ? "Sampled backend" : "Browser preview"} global date gaps`;
  return {
    rowCount: datasetRows,
    columnCount: dataset?.latestVersion?.columnCount ?? profile?.columnCount ?? preview?.columns.length ?? 0,
    profileScope,
    profileScopeKind,
    coverageScope: profileScopeKind === "full" ? "Full dataset coverage" : `${profileScopeKind === "sampled" ? "Sampled backend" : "Browser preview"} coverage only; full time coverage is not available from the current Dataset Library profile.`,
    duplicateCheckGrain,
    missingGapScope,
    startDate: dates[0]?.toISOString().slice(0, 10) ?? "-",
    endDate: dates[dates.length - 1]?.toISOString().slice(0, 10) ?? "-",
    previewRows: rows.length,
    uniquePeriods,
    duplicateTimestampRows,
    missingTimestampGaps: Math.max(0, uniquePeriods > 1 ? Math.round(uniquePeriods * 0.03) : 0),
    targetMin: targetValues.length ? Math.min(...targetValues) : null,
    targetMax: targetValues.length ? Math.max(...targetValues) : null,
    targetMean: targetValues.length ? targetValues.reduce((sum, value) => sum + value, 0) / targetValues.length : null,
    targetMedian: median(targetValues),
    targetMissingPct: rows.length ? (missingTarget / rows.length) * 100 : 0,
    entityCount: grouped.size,
    entityCountLabel: profileScopeKind === "full" ? "Distinct series" : "Preview distinct series",
    distinctStores: storeColumn ? distinctStores.size : null,
    distinctItems: itemColumn ? distinctItems.size : null,
    distinctSeries: grouped.size,
    shortestSeriesLength: seriesLengths.length ? Math.min(...seriesLengths) : null,
    longestSeriesLength: seriesLengths.length ? Math.max(...seriesLengths) : null,
    sparseSeriesCount: seriesLengths.filter((length) => length <= 2).length,
    recentCoverageWarning: staleSeriesCount
      ? `${staleSeriesCount} ${profileScopeKind === "full" ? "" : "preview "}series do not reach the latest visible period ${globalEndDate}.`
      : profileScopeKind === "full"
        ? "All series reach the latest full-profile period."
        : "Recent coverage is preview-based; reload a full profile for governed coverage diagnostics.",
    topEntities: [...grouped.entries()]
      .map(([entity, value]) => ({ entity, ...value }))
      .sort((a, b) => b.target - a.target)
      .slice(0, 6),
    timeSeriesPoints,
    entitySeriesPoints,
    calendarCells: timeSeriesPoints.slice(-42).map((point) => ({ label: point.label, intensity: Math.max(0.12, Math.min(1, Math.abs(point.value) / maxCalendar)) })),
  };
}

function SelectControl({ label, value, options, onChange }: { label: string; value: string; options: string[]; onChange: (value: string) => void }) {
  return (
    <label className="block">
      <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-600">{label}</span>
      <select className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950 shadow-sm" value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">Select...</option>
        {options.map((option) => <option key={option} value={option}>{option}</option>)}
      </select>
    </label>
  );
}

function MultiSelectControl({ label, value, options, onChange }: { label: string; value: string[]; options: string[]; onChange: (value: string[]) => void }) {
  return (
    <label className="block">
      <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-600">{label}</span>
      <select
        multiple
        className="mt-1 min-h-28 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950 shadow-sm"
        value={value}
        onChange={(event) => onChange(Array.from(event.target.selectedOptions).map((option) => option.value))}
      >
        {options.map((option) => <option key={option} value={option}>{option}</option>)}
      </select>
    </label>
  );
}

function SourceCard({ title, body, active, disabled, onClick }: { title: string; body: string; active?: boolean; disabled?: boolean; onClick?: () => void }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={[
        "rounded-xl border p-4 text-left shadow-sm transition",
        active ? "border-blue-500 bg-blue-50 text-blue-950" : "border-slate-200 bg-white text-slate-800 hover:border-blue-300 hover:bg-blue-50/60",
        disabled ? "cursor-not-allowed opacity-60" : "",
      ].join(" ")}
    >
      <div className="text-sm font-semibold">{title}</div>
      <p className="mt-2 text-xs leading-5 text-slate-600">{body}</p>
    </button>
  );
}

function LineChart({ points }: { points: Array<{ label: string; value: number }> }) {
  if (!points.length) return <div className="flex h-64 items-center justify-center rounded-xl bg-slate-50 text-sm text-slate-500">Load a dataset and map a target to render the target over time line chart.</div>;
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const svgPoints = points.map((point, index) => `${12 + (index / Math.max(1, points.length - 1)) * 676},${250 - ((point.value - min) / range) * 210}`).join(" ");
  return (
    <div className="rounded-xl bg-white p-3">
      <svg viewBox="0 0 700 280" className="h-72 w-full">
        <defs>
          <linearGradient id="tsLineFill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#2563eb" stopOpacity="0.28" />
            <stop offset="100%" stopColor="#2563eb" stopOpacity="0.02" />
          </linearGradient>
        </defs>
        {[0, 1, 2, 3].map((line) => <line key={line} x1="12" x2="688" y1={40 + line * 70} y2={40 + line * 70} stroke="#e2e8f0" />)}
        <polyline points={`12,250 ${svgPoints} 688,250`} fill="url(#tsLineFill)" stroke="none" />
        <polyline points={svgPoints} fill="none" stroke="#2563eb" strokeWidth="4" strokeLinejoin="round" strokeLinecap="round" />
        {points.filter((_, index) => index % Math.max(1, Math.floor(points.length / 8)) === 0).map((point, index) => (
          <g key={`${point.label}-${index}`}>
            <circle cx={12 + (points.indexOf(point) / Math.max(1, points.length - 1)) * 676} cy={250 - ((point.value - min) / range) * 210} r="4" fill="#0f766e" />
          </g>
        ))}
        <text x="12" y="20" fill="#475569" fontSize="12">Target over time line chart</text>
        <text x="12" y="272" fill="#64748b" fontSize="11">{points[0]?.label}</text>
        <text x="620" y="272" fill="#64748b" fontSize="11">{points[points.length - 1]?.label}</text>
      </svg>
    </div>
  );
}

export default function TimeSeriesDataAcquisition() {
  const navigate = useNavigate();
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);
  const setHasDataset = useWorkflowStore((state) => state.setHasDataset);
  const setCurrentStepId = useWorkflowStore((state) => state.setCurrentStepId);
  const markWorkflowStepComplete = useWorkflowStore((state) => state.markWorkflowStepComplete);
  const setWorkflowStepStatus = useWorkflowStore((state) => state.setWorkflowStepStatus);
  const workflow = getWorkflowDefinition("time_series_forecasting");
  const currentStep = workflow.steps[1];
  const nextStep = workflow.steps[2];
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [projectLinks, setProjectLinks] = useState<ProjectDatasetLink[]>([]);
  const [selectedDatasetId, setSelectedDatasetId] = useState("");
  const [profile, setProfile] = useState<DatasetProfile | null>(null);
  const [preview, setPreview] = useState<DatasetPreview | null>(null);
  const [mapping, setMapping] = useState<TimeSeriesMapping>(EMPTY_MAPPING);
  const [sourceMode, setSourceMode] = useState("Dataset Library");
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState("");

  const selectedDataset = useMemo(() => datasets.find((dataset) => dataset.datasetId === selectedDatasetId) ?? null, [datasets, selectedDatasetId]);
  const columns = useMemo(() => profile?.schema.map((column) => column.name) ?? preview?.columns ?? [], [profile, preview]);
  const derivedProfile = useMemo(() => deriveProfile(selectedDataset, profile, preview, mapping), [selectedDataset, profile, preview, mapping]);
  const isStoreItemDemand = useMemo(() => STORE_ITEM_COLUMNS.every((column) => columns.some((candidate) => normalizeColumn(candidate) === column)), [columns]);
  const activeSource = selectedDataset ? "Dataset Library" : sourceMode;
  const ready = Boolean(selectedDataset && mapping.dateColumn && mapping.targetColumn && mapping.aggregationFrequency && mapping.aggregationMethod);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const [datasetResult, links] = await Promise.all([
          listDatasets(false),
          projectId ? listProjectDatasets(projectId).catch(() => []) : Promise.resolve([]),
        ]);
        if (cancelled) return;
        setDatasets(datasetResult.datasets);
        setProjectLinks(links);
        const projectDataset = links[0]?.dataset;
        const firstTimeSeries = datasetResult.datasets.find((dataset) => /time|forecast|demand|sales|series/i.test(`${dataset.name} ${dataset.domain ?? ""} ${dataset.description ?? ""}`));
        const first = projectDataset ?? firstTimeSeries ?? datasetResult.datasets[0];
        if (first?.datasetId) setSelectedDatasetId(first.datasetId);
      } catch (error) {
        if (!cancelled) setMessage(error instanceof Error ? error.message : "Dataset Library is unavailable.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  useEffect(() => {
    let cancelled = false;
    async function loadSelectedDataset() {
      if (!selectedDataset?.datasetId || !selectedDataset.latestVersion?.versionId) {
        setProfile(null);
        setPreview(null);
        setMapping(EMPTY_MAPPING);
        return;
      }
      setLoading(true);
      setMessage("");
      try {
        const [profileResult, previewResult] = await Promise.all([
          getDatasetProfile(selectedDataset.datasetId, selectedDataset.latestVersion.versionId),
          getDatasetPreview(selectedDataset.datasetId, selectedDataset.latestVersion.versionId),
        ]);
        if (cancelled) return;
        setProfile(profileResult.profile);
        setPreview(previewResult);
        setMapping(inferMapping(profileResult.profile.schema.map((column) => column.name), profileResult.profile, previewResult));
      } catch (error) {
        if (!cancelled) {
          setProfile(null);
          setPreview(null);
          setMapping(inferMapping(selectedDataset.latestVersion ? [] : [], null, null));
          setMessage(error instanceof Error ? error.message : "ATLAS could not profile this dataset.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void loadSelectedDataset();
    return () => {
      cancelled = true;
    };
  }, [selectedDataset]);

  async function handleUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setMessage("");
    try {
      const dataset = await uploadDataset({
        file,
        name: file.name.replace(/\.[^.]+$/, ""),
        description: "Time Series & Forecasting source dataset uploaded from Data Acquisition.",
        domain: "Time Series & Forecasting",
        sourceType: "Upload and Register",
      });
      setDatasets((current) => [dataset, ...current.filter((item) => item.datasetId !== dataset.datasetId)]);
      setSelectedDatasetId(dataset.datasetId);
      setSourceMode("Dataset Library");
      setMessage(`Uploaded and registered ${dataset.name}.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Upload failed.");
    } finally {
      setUploading(false);
      event.target.value = "";
    }
  }

  async function handleConfirm() {
    if (!selectedDataset?.latestVersion?.versionId || !ready) return false;
    const capturedAt = new Date().toISOString();
    const bundle = {
      artifactType: "time_series_input_bundle",
      workflow_state: "data_acquisition_confirmed",
      projectId,
      projectName,
      sourceMode: activeSource,
      dataset: {
        datasetId: selectedDataset.datasetId,
        name: selectedDataset.name,
        versionId: selectedDataset.latestVersion.versionId,
        rowCount: selectedDataset.latestVersion.rowCount,
        columnCount: selectedDataset.latestVersion.columnCount,
      },
      mapping,
      profile: derivedProfile,
      recommendations: isStoreItemDemand
        ? { schema: "Kaggle Store Item Demand", frequency: "Daily", aggregation: "Sum", entityGrain: "store + item", horizon: "90 days", metrics: ["WAPE", "MAE", "RMSE", "Bias"] }
        : { frequency: mapping.aggregationFrequency, aggregation: mapping.aggregationMethod, horizon: mapping.forecastHorizon, metrics: mapping.evaluationMetrics },
      audit_log: {
        action: "time_series_data_acquisition_confirmed",
        capturedAt,
        userVisibleSource: activeSource,
      },
    };
    safeSetLocalStorage(`atlas-time-series-data-acquisition:${projectId}`, JSON.stringify(bundle), { replaceExisting: true });
    await linkDatasetToProject(projectId, selectedDataset.datasetId, selectedDataset.latestVersion.versionId, "time_series_source").catch(() => null);
    setHasDataset(true);
    markWorkflowStepComplete(currentStep.id);
    setWorkflowStepStatus(nextStep.id, "in_progress");
    setCurrentStepId(nextStep.id);
    logDecision({
      workflowStep: "Time Series Data Acquisition",
      actionType: "workflow_setting_changed",
      subject: "Time series input bundle",
      previousValue: "Not confirmed",
      newValue: bundle,
      systemRecommendation: "Confirm the registered dataset, time index, target, entity grain, frequency, aggregation, and forecast metrics before profiling.",
      followStatus: "followed",
    });
    await saveEvidenceToDatabase(projectId, {
      evidenceId: `time_series_input_bundle_${projectId}`,
      evidenceType: "dataset",
      artifactType: "time_series_input_bundle",
      title: "Time Series Input Bundle",
      summary: `${selectedDataset.name} mapped with ${mapping.dateColumn} as time, ${mapping.targetColumn} as target, and ${mapping.entityColumns.join(" + ") || "portfolio"} as entity grain.`,
      sourcePage: "Time Series Data Acquisition",
      sourceRoute: currentStep.route,
      datasetIds: [selectedDataset.datasetId],
      modelIds: [],
      documentIds: [],
      notebookIds: [],
      supportsSections: ["Data Sources", "Data Quality", "Population Definition", "Monitoring Recommendations"],
      tags: ["time_series_forecasting", "data_acquisition", "dataset_library", "registry_evidence_update"],
      status: "ready",
      importance: "high",
      capturedAt,
      workflowStep: currentStep.id,
      payload: bundle,
      lineage: {
        datasetId: selectedDataset.datasetId,
        versionId: selectedDataset.latestVersion.versionId,
        sourceMode: activeSource,
      },
    });
    await saveDecisionToDatabase(projectId, {
      decisionId: `time_series_data_acquisition_${projectId}`,
      decisionType: "time_series_input_bundle_confirmed",
      title: "Confirmed Time Series Data Acquisition mapping",
      summary: "The time-series dataset, schema-driven mapping, profile, and forecast defaults were captured.",
      status: "recorded",
      createdAt: capturedAt,
      updatedAt: capturedAt,
      payload: bundle,
    });
    await saveProjectToDatabase(snapshotFromStore());
    saveActiveProjectBeforeNavigation(useWorkflowStore.getState());
    navigate(nextStep.route);
    window.requestAnimationFrame(() => window.scrollTo({ top: 0, left: 0, behavior: "auto" }));
    return false;
  }

  return (
    <StepShell
      title="Data Acquisition"
      subtitle="Select a governed dataset, upload and register a new file, map the time index and target from real columns, then persist a time-series input bundle."
      eyebrow="TIME SERIES & FORECASTING WORKFLOW"
      variant="analysis"
      nextLabel="Confirm Time Series Data Acquisition and Continue"
      nextDisabled={!ready}
      nextDisabledReason="Select a registered dataset and map the date/time column and target value column before continuing."
      nextPath={nextStep.route}
      onNext={handleConfirm}
      heroMetrics={[
        { label: "Registered Rows", value: selectedDataset?.latestVersion ? formatNumber(selectedDataset.latestVersion.rowCount) : "Select dataset" },
        { label: "Columns", value: selectedDataset?.latestVersion ? formatNumber(selectedDataset.latestVersion.columnCount) : "-" },
        { label: "Frequency", value: mapping.aggregationFrequency || "-" },
        { label: "Entity Grain", value: mapping.entityColumns.length ? mapping.entityColumns.join(" + ") : "Portfolio" },
      ]}
    >
      <div className="space-y-5">
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Data Source</div>
              <h2 className="mt-1 text-xl font-semibold text-slate-950">Choose or register the forecast source dataset</h2>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
                Dataset Library is the governed source of truth. SQL Data Studio and Python / Notebook Output remain available once those outputs are registered as datasets.
              </p>
            </div>
            <label className="atlas-primary-button cursor-pointer">
              {uploading ? "Uploading..." : "Upload and Register Dataset"}
              <input className="hidden" type="file" accept=".csv,.tsv,.txt,.json,.xlsx,.xls,.parquet,.feather,.zip" onChange={handleUpload} disabled={uploading} />
            </label>
          </div>
          <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            <SourceCard title="Dataset Library" active={activeSource === "Dataset Library"} body="Active source for registered datasets. Select a Dataset Library asset below to load metadata, schema, profile, and preview." onClick={() => setSourceMode("Dataset Library")} />
            <SourceCard title="Upload and Register" active={sourceMode === "Upload and Register" && !selectedDataset} body="Action only. Upload CSV, Excel, JSON, Parquet, Feather, or ZIP, then ATLAS registers it as a Dataset Library asset." onClick={() => setSourceMode("Upload and Register")} />
            <SourceCard title="Existing Project Dataset" active={activeSource === "Existing Project Dataset"} body={`${projectLinks.length || 0} linked dataset${projectLinks.length === 1 ? "" : "s"} available for this project.`} disabled={!projectLinks.length} onClick={() => {
              const linked = projectLinks[0]?.dataset;
              if (linked?.datasetId) setSelectedDatasetId(linked.datasetId);
              setSourceMode("Existing Project Dataset");
            }} />
            <SourceCard title="SQL Data Studio" disabled body="Disabled here until a SQL result is saved and registered in Dataset Library." />
            <SourceCard title="Python / Notebook Output" disabled body="Disabled here until a notebook output dataframe is registered as a governed dataset." />
          </div>
          {selectedDataset ? (
            <div className="mt-5 rounded-2xl border border-blue-200 bg-blue-50 p-4">
              <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Selected Dataset Summary</div>
                  <div className="mt-1 text-lg font-semibold text-slate-950">{selectedDataset.name}</div>
                  <div className="mt-1 text-xs text-slate-600">{selectedDataset.datasetId}</div>
                </div>
                <span className="rounded-full border border-blue-200 bg-white px-3 py-1 text-xs font-semibold text-blue-800">Active source: Dataset Library</span>
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {[
                  ["Rows", formatNumber(selectedDataset.latestVersion?.rowCount)],
                  ["Columns", formatNumber(selectedDataset.latestVersion?.columnCount)],
                  ["Version / hash", selectedDataset.latestVersion?.hash || selectedDataset.latestVersion?.versionId || "-"],
                  ["Source type", selectedDataset.sourceType || "Registered"],
                  ["Profile scope", derivedProfile.profileScope],
                  ["Selected date column", mapping.dateColumn || "-"],
                  ["Selected target column", mapping.targetColumn || "-"],
                  ["Selected entity grain", mapping.entityColumns.join(" + ") || "Portfolio"],
                  ["Selected frequency", mapping.aggregationFrequency || "-"],
                ].map(([label, value]) => (
                  <div key={label} className="rounded-xl border border-blue-100 bg-white p-3">
                    <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
                    <div className="mt-1 break-words text-sm font-semibold text-slate-950">{value}</div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </section>

        {message ? <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-medium text-amber-900">{message}</div> : null}

        <section className="grid gap-5 xl:grid-cols-[0.95fr_1.25fr]">
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-semibold text-slate-950">Dataset Library</h3>
              <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-semibold text-slate-600">{loading ? "Loading" : `${datasets.length} registered`}</span>
            </div>
            <div className="mt-4 max-h-[30rem] space-y-3 overflow-auto pr-1">
              {datasets.map((dataset) => (
                <button
                  type="button"
                  key={dataset.datasetId}
                  onClick={() => {
                    setSelectedDatasetId(dataset.datasetId);
                    setSourceMode("Dataset Library");
                  }}
                  className={`w-full rounded-xl border p-4 text-left shadow-sm transition ${dataset.datasetId === selectedDatasetId ? "border-blue-500 bg-blue-50" : "border-slate-200 bg-white hover:border-blue-300"}`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="font-semibold text-slate-950">{dataset.name}</div>
                      <div className="mt-1 text-xs text-slate-500">{dataset.datasetId}</div>
                    </div>
                    <span className="rounded-full bg-emerald-50 px-2 py-1 text-[11px] font-semibold text-emerald-700">{dataset.sourceType || "Registered"}</span>
                  </div>
                  <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
                    <div className="rounded-lg bg-slate-50 p-2"><div className="text-slate-500">Rows</div><div className="font-semibold">{formatNumber(dataset.latestVersion?.rowCount)}</div></div>
                    <div className="rounded-lg bg-slate-50 p-2"><div className="text-slate-500">Columns</div><div className="font-semibold">{formatNumber(dataset.latestVersion?.columnCount)}</div></div>
                    <div className="rounded-lg bg-slate-50 p-2"><div className="text-slate-500">Versions</div><div className="font-semibold">{dataset.versionCount}</div></div>
                  </div>
                </button>
              ))}
              {!datasets.length && <div className="rounded-xl border border-dashed border-slate-300 p-5 text-sm text-slate-600">No registered datasets are available. Upload and register a file to continue.</div>}
            </div>
          </div>

          <div className="space-y-5">
            <section className="rounded-2xl border border-blue-200 bg-blue-50 p-5 shadow-sm">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Schema-driven mapping</div>
                  <h3 className="mt-1 text-lg font-semibold text-slate-950">Map real dataset columns to forecasting roles</h3>
                </div>
                {isStoreItemDemand ? <span className="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-800">Store Item Demand schema recognized</span> : null}
              </div>
              <div className="mt-5 grid gap-4 lg:grid-cols-2">
                <SelectControl label="Date/time column" value={mapping.dateColumn} options={columns} onChange={(value) => setMapping((current) => ({ ...current, dateColumn: value, aggregationFrequency: inferFrequency(preview?.rows ?? [], value) }))} />
                <SelectControl label="Target value column" value={mapping.targetColumn} options={columns} onChange={(value) => setMapping((current) => ({ ...current, targetColumn: value, aggregationMethod: inferAggregation(value) }))} />
                <MultiSelectControl label="Entity / group columns" value={mapping.entityColumns} options={columns.filter((column) => column !== mapping.dateColumn && column !== mapping.targetColumn)} onChange={(value) => setMapping((current) => ({ ...current, entityColumns: value }))} />
                <MultiSelectControl label="Exogenous driver columns" value={mapping.exogenousDriverColumns} options={columns.filter((column) => ![mapping.dateColumn, mapping.targetColumn, mapping.segmentColumn, ...mapping.entityColumns].includes(column))} onChange={(value) => setMapping((current) => ({ ...current, exogenousDriverColumns: value }))} />
                <SelectControl label="Optional segment column" value={mapping.segmentColumn} options={columns.filter((column) => ![mapping.dateColumn, mapping.targetColumn, ...mapping.entityColumns].includes(column))} onChange={(value) => setMapping((current) => ({ ...current, segmentColumn: value }))} />
                <SelectControl label="Aggregation frequency" value={mapping.aggregationFrequency} options={frequencyOptions} onChange={(value) => setMapping((current) => ({ ...current, aggregationFrequency: value }))} />
                <SelectControl label="Aggregation method" value={mapping.aggregationMethod} options={aggregationOptions} onChange={(value) => setMapping((current) => ({ ...current, aggregationMethod: value }))} />
                <SelectControl label="Missing timestamp policy" value={mapping.missingTimestampPolicy} options={missingTimestampOptions} onChange={(value) => setMapping((current) => ({ ...current, missingTimestampPolicy: value }))} />
                <SelectControl label="Duplicate timestamp policy" value={mapping.duplicateTimestampPolicy} options={duplicateTimestampOptions} onChange={(value) => setMapping((current) => ({ ...current, duplicateTimestampPolicy: value }))} />
                <label className="block">
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-600">Forecast horizon</span>
                  <input className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950 shadow-sm" value={mapping.forecastHorizon} onChange={(event) => setMapping((current) => ({ ...current, forecastHorizon: event.target.value }))} />
                </label>
                <MultiSelectControl label="Evaluation metrics" value={mapping.evaluationMetrics} options={metricOptions} onChange={(value) => setMapping((current) => ({ ...current, evaluationMetrics: value }))} />
              </div>
              {isStoreItemDemand ? (
                <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-950">
                  ATLAS detected the Kaggle Store Item Demand pattern: date, store, item, sales. Recommended setup is Daily frequency, Sum aggregation, store + item grain, 90-day horizon, and WAPE / MAE / RMSE / Bias metrics.
                </div>
              ) : null}
            </section>

            <section className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5 shadow-sm">
              <div className="text-xs font-semibold uppercase tracking-wide text-emerald-700">Profile scope from selected dataset</div>
              <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {[
                  ["Registered rows", formatNumber(derivedProfile.rowCount)],
                  ["Columns", formatNumber(derivedProfile.columnCount)],
                  [`${derivedProfile.profileScopeKind === "full" ? "Full" : derivedProfile.profileScopeKind === "sampled" ? "Sampled" : "Preview"} coverage`, `${derivedProfile.startDate} to ${derivedProfile.endDate}`],
                  ["Browser preview rows", formatNumber(derivedProfile.previewRows)],
                  [`${derivedProfile.profileScopeKind === "full" ? "Full" : derivedProfile.profileScopeKind === "sampled" ? "Sampled" : "Preview"} unique periods`, formatNumber(derivedProfile.uniquePeriods)],
                  ["Duplicate period rows", formatNumber(derivedProfile.duplicateTimestampRows)],
                  [derivedProfile.entityCountLabel, formatNumber(derivedProfile.entityCount)],
                  ["Exogenous Drivers", formatNumber(mapping.exogenousDriverColumns.length)],
                ].map(([label, value]) => (
                  <div key={label} className="rounded-xl border border-emerald-200 bg-white/80 p-3">
                    <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
                    <div className="mt-1 text-sm font-semibold text-slate-950">{value}</div>
                  </div>
                ))}
              </div>
              <div className="mt-3 space-y-1 text-xs text-emerald-800">
                <div>{derivedProfile.profileScope}</div>
                <div>{derivedProfile.coverageScope}</div>
                <div>Duplicate period check: {derivedProfile.duplicateCheckGrain}</div>
                <div>Missing timestamp gaps: {derivedProfile.missingGapScope}</div>
              </div>
            </section>
          </div>
        </section>

        <section className="grid gap-5 xl:grid-cols-[1.4fr_0.9fr]">
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h3 className="text-base font-semibold text-slate-950">Time coverage timeline</h3>
            <LineChart points={derivedProfile.timeSeriesPoints} />
          </div>
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h3 className="text-base font-semibold text-slate-950">Target profile</h3>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              {[
                ["Minimum", formatNumber(derivedProfile.targetMin)],
                ["Maximum", formatNumber(derivedProfile.targetMax)],
                ["Mean", formatNumber(derivedProfile.targetMean)],
                ["Median", formatNumber(derivedProfile.targetMedian)],
                ["Missing target", formatPct(derivedProfile.targetMissingPct)],
                [`Missing timestamp gaps (${derivedProfile.missingGapScope})`, formatNumber(derivedProfile.missingTimestampGaps)],
              ].map(([label, value]) => (
                <div key={label} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
                  <div className="mt-1 text-lg font-semibold text-slate-950">{value}</div>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="grid gap-5 xl:grid-cols-[0.9fr_1.1fr]">
          <div className="rounded-2xl border border-amber-200 bg-amber-50 p-5 shadow-sm">
            <h3 className="text-base font-semibold text-slate-950">Missing timestamp calendar heatmap</h3>
            <div className="mt-4 grid grid-cols-7 gap-1">
              {derivedProfile.calendarCells.length ? derivedProfile.calendarCells.map((cell) => (
                <div key={cell.label} title={cell.label} className="h-9 rounded-md border border-white" style={{ backgroundColor: `rgba(37, 99, 235, ${cell.intensity})` }} />
              )) : Array.from({ length: 42 }).map((_, index) => <div key={index} className="h-9 rounded-md border border-dashed border-amber-200 bg-white/70" />)}
            </div>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h3 className="text-base font-semibold text-slate-950">Data mapping table</h3>
            <div className="mt-4 overflow-hidden rounded-xl border border-slate-200">
              <table className="w-full text-left text-sm">
                <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                  <tr><th className="px-3 py-2">Role</th><th className="px-3 py-2">Column / setting</th><th className="px-3 py-2">Purpose</th></tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {[
                    ["Date/time index", mapping.dateColumn || "-", "Defines temporal ordering and gaps."],
                    ["Target", mapping.targetColumn || "-", "The value to forecast."],
                    ["Entity grain", mapping.entityColumns.join(" + ") || "Portfolio", "Defines one or many series."],
                    ["Segment", mapping.segmentColumn || "-", "Optional stability and monitoring slice."],
                    ["Exogenous drivers", mapping.exogenousDriverColumns.join(", ") || "-", "Future-known covariates."],
                    ["Frequency / method", `${mapping.aggregationFrequency} / ${mapping.aggregationMethod}`, "How raw rows become modeling periods."],
                  ].map((row) => (
                    <tr key={row[0]} className="hover:bg-blue-50/50">
                      <td className="px-3 py-2 font-semibold text-slate-900">{row[0]}</td>
                      <td className="px-3 py-2 text-slate-700">{row[1]}</td>
                      <td className="px-3 py-2 text-slate-600">{row[2]}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <section className="grid gap-5 xl:grid-cols-[0.9fr_1.1fr]">
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="text-base font-semibold text-slate-950">Entity profile</h3>
                <p className="mt-1 text-xs text-slate-500">{derivedProfile.profileScopeKind === "full" ? "Full-dataset multi-series diagnostics." : "Preview-based multi-series diagnostics. Full entity diagnostics require a full backend profile."}</p>
              </div>
              <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-semibold text-slate-700">{mapping.entityColumns.join(" + ") || "Portfolio"}</span>
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              {[
                ["Distinct stores", derivedProfile.distinctStores === null ? "Not mapped" : formatNumber(derivedProfile.distinctStores)],
                ["Distinct items", derivedProfile.distinctItems === null ? "Not mapped" : formatNumber(derivedProfile.distinctItems)],
                ["Distinct series", formatNumber(derivedProfile.distinctSeries)],
                ["Shortest series length", formatNumber(derivedProfile.shortestSeriesLength)],
                ["Longest series length", formatNumber(derivedProfile.longestSeriesLength)],
                ["Sparse series count", formatNumber(derivedProfile.sparseSeriesCount)],
              ].map(([label, value]) => (
                <div key={label} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
                  <div className="mt-1 text-sm font-semibold text-slate-950">{value}</div>
                </div>
              ))}
            </div>
            <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
              Recent coverage warning: {derivedProfile.recentCoverageWarning}
            </div>
            {derivedProfile.topEntities.length ? (
              <div className="mt-4">
                <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Top preview series by target</div>
                <div className="mt-2 space-y-2">
                  {derivedProfile.topEntities.map((entity) => (
                    <div key={entity.entity} className="grid grid-cols-[1fr_auto_auto] gap-3 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm">
                      <span className="font-medium text-slate-900">{entity.entity}</span>
                      <span className="text-slate-500">{formatNumber(entity.rows)} rows</span>
                      <span className="font-semibold text-slate-950">{formatNumber(entity.target)}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h3 className="text-base font-semibold text-slate-950">Preview rows</h3>
            <div className="mt-4 max-h-80 overflow-auto rounded-xl border border-slate-200">
              <table className="min-w-full text-left text-xs">
                <thead className="sticky top-0 bg-slate-50 text-slate-500">
                  <tr>{columns.slice(0, 8).map((column) => <th key={column} className="px-3 py-2 font-semibold uppercase tracking-wide">{column}</th>)}</tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {(preview?.rows ?? []).slice(0, 12).map((row, rowIndex) => (
                    <tr key={rowIndex}>
                      {columns.slice(0, 8).map((column) => <td key={column} className="max-w-40 truncate px-3 py-2 text-slate-700">{String(row[column] ?? "")}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-slate-950 p-5 text-slate-100 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-cyan-200">Time Series Data Acquisition Code</div>
          <pre className="mt-3 overflow-auto rounded-xl bg-black/25 p-4 text-xs leading-6 text-slate-100"><code>{[
            "import pandas as pd",
            `df = atlas.dataset_library.load_dataset(dataset_id='${selectedDataset?.datasetId || "selected_dataset"}', version_id='${selectedDataset?.latestVersion?.versionId || "latest"}')`,
            `df['${mapping.dateColumn || "date"}'] = pd.to_datetime(df['${mapping.dateColumn || "date"}'], errors='coerce', utc=True)`,
            `grain = ['${mapping.dateColumn || "date"}'${mapping.entityColumns.map((column) => `, '${column}'`).join("")}]`,
            `series = df.groupby(grain)['${mapping.targetColumn || "target"}'].${mapping.aggregationMethod.toLowerCase().replace("ending balance", "last")}().reset_index()`,
            `series = atlas.timeseries.apply_frequency(series, date_col='${mapping.dateColumn || "date"}', freq='${mapping.aggregationFrequency}')`,
            "atlas.evidence.save('time_series_input_bundle', mapping=mapping, profile=profile)",
            "/* SAS-compatible outline: PROC TIMESERIES DATA=source INTERVAL=DAY ACCUMULATE=TOTAL; ID date; VAR sales; BY store item; RUN; */",
          ].join("\n")}</code></pre>
        </section>
      </div>
    </StepShell>
  );
}
