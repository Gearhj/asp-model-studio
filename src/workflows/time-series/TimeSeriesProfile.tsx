import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import StepShell from "../../components/StepShell";
import { getWorkflowDefinition } from "../../config/workflows";
import { logDecision } from "../../lib/decisionJournal";
import { saveActiveProjectBeforeNavigation } from "../../lib/localProjects";
import { saveEvidenceToDatabase, saveProjectToDatabase } from "../../lib/serverPersistence";
import { useWorkflowStore, type WorkflowProjectSnapshot } from "../../state/useWorkflowStore";
import { requestAnalyticalRun } from "../../api/analyticsEngine";
import type { AnalyticalResult } from "../../types/analyticsEngine";
import { AnalyticalResultCard } from "../../components/analytics/AnalyticalResultCard";
import { AnalyticalChart } from "../../components/analytics/AnalyticalChart";
import { DiagnosticTable } from "../../components/analytics/DiagnosticTable";
import { InterpretationPanel } from "../../components/analytics/InterpretationPanel";

type SeriesPoint = { label: string; value: number };
type InputBundle = {
  artifactType?: string;
  projectId?: string;
  dataset?: { datasetId?: string; name?: string; versionId?: string; rowCount?: number; columnCount?: number };
  mapping?: {
    dateColumn?: string;
    targetColumn?: string;
    entityColumns?: string[];
    aggregationFrequency?: string;
    aggregationMethod?: string;
  };
  profile?: {
    profileScope?: string;
    profileScopeKind?: "full" | "sampled" | "preview";
    startDate?: string;
    endDate?: string;
    rowCount?: number;
    uniquePeriods?: number;
    distinctSeries?: number;
    topEntities?: Array<{ entity: string; rows: number; target: number }>;
    timeSeriesPoints?: SeriesPoint[];
    entitySeriesPoints?: Record<string, SeriesPoint[]>;
  };
};

type AnomalyPoint = SeriesPoint & { zScore: number; rollingMean: number | null };

const sensitivityThreshold = {
  Low: 3,
  Medium: 2.5,
  High: 2,
} as const;

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

function readBundle(projectId: string): InputBundle | null {
  try {
    const raw = window.localStorage.getItem(`atlas-time-series-data-acquisition:${projectId}`);
    return raw ? JSON.parse(raw) as InputBundle : null;
  } catch {
    return null;
  }
}

function formatNumber(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(value);
}

function mean(values: number[]) {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
}

function stdDev(values: number[]) {
  const avg = mean(values);
  if (avg === null || values.length < 2) return null;
  const variance = values.reduce((sum, value) => sum + (value - avg) ** 2, 0) / (values.length - 1);
  return Math.sqrt(variance);
}

function rollingMean(points: SeriesPoint[], windowSize: number) {
  return points.map((_, index) => mean(points.slice(Math.max(0, index - windowSize + 1), index + 1).map((point) => point.value)));
}

function rollingStd(points: SeriesPoint[], windowSize: number) {
  return points.map((_, index) => stdDev(points.slice(Math.max(0, index - windowSize + 1), index + 1).map((point) => point.value)));
}

function detectAnomalies(points: SeriesPoint[], windowSize: number, threshold: number): AnomalyPoint[] {
  const rollMean = rollingMean(points, windowSize);
  const rollStd = rollingStd(points, windowSize);
  return points
    .map((point, index) => {
      const baseline = rollMean[index];
      const sigma = rollStd[index];
      const zScore = baseline !== null && sigma && sigma > 0 ? Math.abs((point.value - baseline) / sigma) : 0;
      return { ...point, zScore, rollingMean: baseline };
    })
    .filter((point) => point.zScore >= threshold);
}

function autocorrelation(values: number[], lag: number) {
  if (values.length <= lag + 2) return null;
  const avg = mean(values);
  if (avg === null) return null;
  const numerator = values.slice(lag).reduce((sum, value, index) => sum + (value - avg) * (values[index] - avg), 0);
  const denominator = values.reduce((sum, value) => sum + (value - avg) ** 2, 0);
  return denominator ? numerator / denominator : null;
}

function trendDirection(points: SeriesPoint[]) {
  if (points.length < 4) return "Short history";
  const first = mean(points.slice(0, Math.max(2, Math.floor(points.length / 3))).map((point) => point.value)) ?? 0;
  const last = mean(points.slice(-Math.max(2, Math.floor(points.length / 3))).map((point) => point.value)) ?? 0;
  const delta = last - first;
  const tolerance = Math.max(1, Math.abs(first) * 0.03);
  if (delta > tolerance) return "Increasing";
  if (delta < -tolerance) return "Decreasing";
  return "Flat";
}

function seasonalRows(points: SeriesPoint[], mode: "day" | "month") {
  const buckets = new Map<string, number[]>();
  for (const point of points) {
    const date = new Date(point.label);
    if (Number.isNaN(date.getTime())) continue;
    const key = mode === "day"
      ? ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][date.getUTCDay()]
      : date.toLocaleString("en-US", { month: "short", timeZone: "UTC" });
    const values = buckets.get(key) ?? [];
    values.push(point.value);
    buckets.set(key, values);
  }
  const order = mode === "day" ? ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] : ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return order
    .filter((key) => buckets.has(key))
    .map((key) => ({ label: key, value: mean(buckets.get(key) ?? []) ?? 0, count: buckets.get(key)?.length ?? 0 }));
}

function strengthFromRows(rows: Array<{ value: number }>) {
  if (rows.length < 2) return 0;
  const values = rows.map((row) => row.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const avg = mean(values) ?? 1;
  return avg ? Math.abs(max - min) / Math.abs(avg) : 0;
}

function Chart({ points, roll, anomalies }: { points: SeriesPoint[]; roll: Array<number | null>; anomalies: AnomalyPoint[] }) {
  const width = 920;
  const height = 360;
  const pad = { left: 68, right: 24, top: 28, bottom: 54 };
  const values = [...points.map((point) => point.value), ...roll.filter((value): value is number => value !== null)];
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 1);
  const range = Math.max(1, max - min);
  const x = (index: number) => pad.left + (index / Math.max(1, points.length - 1)) * (width - pad.left - pad.right);
  const y = (value: number) => pad.top + (1 - (value - min) / range) * (height - pad.top - pad.bottom);
  const actualPath = points.map((point, index) => `${x(index)},${y(point.value)}`).join(" ");
  const rollingPath = roll.map((value, index) => value === null ? null : `${x(index)},${y(value)}`).filter(Boolean).join(" ");
  const anomalyLabels = new Set(anomalies.map((point) => point.label));
  const tickEvery = Math.max(1, Math.floor(points.length / 6));
  return (
    <div className="rounded-2xl border border-blue-200 bg-white p-4 shadow-sm">
      <svg viewBox={`0 0 ${width} ${height}`} className="h-[430px] w-full">
        <rect x="0" y="0" width={width} height={height} rx="18" fill="#f8fafc" />
        {[0, 1, 2, 3, 4].map((line) => {
          const yy = pad.top + line * ((height - pad.top - pad.bottom) / 4);
          const value = max - (line / 4) * range;
          return <g key={line}><line x1={pad.left} x2={width - pad.right} y1={yy} y2={yy} stroke="#dbeafe" /><text x="12" y={yy + 4} fill="#64748b" fontSize="12">{formatNumber(value, 0)}</text></g>;
        })}
        <polyline points={actualPath} fill="none" stroke="#2563eb" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
        <polyline points={rollingPath} fill="none" stroke="#0f766e" strokeWidth="3" strokeDasharray="8 6" strokeLinecap="round" strokeLinejoin="round" />
        {points.map((point, index) => anomalyLabels.has(point.label) ? <circle key={point.label} cx={x(index)} cy={y(point.value)} r="6" fill="#f97316" stroke="#fff7ed" strokeWidth="3" /> : null)}
        {points.map((point, index) => index % tickEvery === 0 || index === points.length - 1 ? (
          <text key={point.label} x={x(index)} y={height - 20} fill="#64748b" fontSize="11" textAnchor="middle">{point.label.slice(5)}</text>
        ) : null)}
        <text x={width / 2} y={height - 4} fill="#334155" fontSize="12" textAnchor="middle">Date / period</text>
        <text x="18" y={height / 2} fill="#334155" fontSize="12" transform={`rotate(-90 18 ${height / 2})`} textAnchor="middle">Target value</text>
        <g transform={`translate(${width - 270} 18)`}>
          <circle cx="0" cy="0" r="5" fill="#2563eb" /><text x="12" y="4" fill="#334155" fontSize="12">Actual</text>
          <line x1="74" x2="100" y1="0" y2="0" stroke="#0f766e" strokeWidth="3" strokeDasharray="6 5" /><text x="108" y="4" fill="#334155" fontSize="12">Rolling mean</text>
          <circle cx="212" cy="0" r="5" fill="#f97316" /><text x="224" y="4" fill="#334155" fontSize="12">Anomaly</text>
        </g>
      </svg>
    </div>
  );
}

function BarRows({ rows, label, suffix = "" }: { rows: Array<{ label: string; value: number; count?: number }>; label: string; suffix?: string }) {
  const max = Math.max(1, ...rows.map((row) => Math.abs(row.value)));
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-[80px_1fr_90px] text-[11px] font-semibold uppercase tracking-wide text-slate-500">
        <span>{label}</span><span>Mean target</span><span>Periods</span>
      </div>
      {rows.map((row) => (
        <div key={row.label} className="grid grid-cols-[80px_1fr_90px] items-center gap-3 text-sm">
          <span className="font-semibold text-slate-800">{row.label}</span>
          <div className="h-3 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-teal-500" style={{ width: `${Math.max(4, Math.min(100, Math.abs(row.value) / max * 100))}%` }} /></div>
          <span className="text-right tabular-nums text-slate-600">{formatNumber(row.value)}{suffix} / {row.count ?? "-"}</span>
        </div>
      ))}
    </div>
  );
}

export default function TimeSeriesProfile() {
  const navigate = useNavigate();
  const projectId = useWorkflowStore((state) => state.projectId);
  const markWorkflowStepComplete = useWorkflowStore((state) => state.markWorkflowStepComplete);
  const setWorkflowStepStatus = useWorkflowStore((state) => state.setWorkflowStepStatus);
  const setCurrentStepId = useWorkflowStore((state) => state.setCurrentStepId);
  const workflow = getWorkflowDefinition("time_series_forecasting");
  const currentStep = workflow.steps[2];
  const nextStep = workflow.steps[3];
  const bundle = useMemo(() => readBundle(projectId), [projectId]);
  const profile = bundle?.profile;
  const mapping = bundle?.mapping;
  const entityOptions = useMemo(() => ["Aggregate", ...Object.keys(profile?.entitySeriesPoints ?? {}).slice(0, 50)], [profile?.entitySeriesPoints]);
  const [selectedEntity, setSelectedEntity] = useState("Aggregate");
  const [dateRange, setDateRange] = useState("Full history");
  const [rollingWindow, setRollingWindow] = useState(7);
  const [sensitivity, setSensitivity] = useState<keyof typeof sensitivityThreshold>("Medium");
  const [engineResult, setEngineResult] = useState<AnalyticalResult | null>(null);
  const [engineMessage, setEngineMessage] = useState("");

  useEffect(() => {
    if (!bundle?.dataset?.datasetId || !mapping?.dateColumn || !mapping?.targetColumn) return;
    let active = true;
    void requestAnalyticalRun("time_series_profile", {
      projectId,
      workflowType: "time_series_forecasting",
      datasetId: bundle.dataset.datasetId,
      datasetVersionId: bundle.dataset.versionId,
      parameters: { timestamp_column: mapping.dateColumn, target_column: mapping.targetColumn, entity_columns: mapping.entityColumns ?? [], frequency: mapping.aggregationFrequency, aggregation: mapping.aggregationMethod, rolling_window: rollingWindow, anomaly_threshold: sensitivityThreshold[sensitivity] },
    }).then((response) => { if (active) setEngineResult(response.result); }).catch((error: unknown) => { if (active) setEngineMessage(error instanceof Error ? error.message : "ATLAS could not refresh the governed time-series profile."); });
    return () => { active = false; };
  }, [bundle?.dataset?.datasetId, bundle?.dataset?.versionId, mapping?.dateColumn, mapping?.targetColumn, projectId, rollingWindow, sensitivity, JSON.stringify(mapping?.entityColumns ?? [])]);

  const selectedSeries = useMemo(() => {
    const entitySeries = selectedEntity !== "Aggregate" ? profile?.entitySeriesPoints?.[selectedEntity] : null;
    const raw = entitySeries?.length ? entitySeries : profile?.timeSeriesPoints ?? [];
    if (dateRange === "Last 12 periods") return raw.slice(-12);
    if (dateRange === "Last 24 periods") return raw.slice(-24);
    if (dateRange === "Last 52 periods") return raw.slice(-52);
    return raw;
  }, [dateRange, profile?.entitySeriesPoints, profile?.timeSeriesPoints, selectedEntity]);

  const rolling = useMemo(() => rollingMean(selectedSeries, rollingWindow), [rollingWindow, selectedSeries]);
  const volatility = useMemo(() => rollingStd(selectedSeries, rollingWindow), [rollingWindow, selectedSeries]);
  const anomalies = useMemo(() => detectAnomalies(selectedSeries, rollingWindow, sensitivityThreshold[sensitivity]), [rollingWindow, selectedSeries, sensitivity]);
  const values = selectedSeries.map((point) => point.value);
  const dayRows = useMemo(() => seasonalRows(selectedSeries, "day"), [selectedSeries]);
  const monthRows = useMemo(() => seasonalRows(selectedSeries, "month"), [selectedSeries]);
  const acfRows = [1, 7, 14, 30].map((lag) => ({ lag, value: autocorrelation(values, lag) }));
  const candidateLags = acfRows.filter((row) => row.value !== null && Math.abs(row.value) >= 0.3).map((row) => row.lag);
  const volatilityValues = volatility.filter((value): value is number => value !== null);
  const highVolatilityThreshold = (mean(volatilityValues) ?? 0) + (stdDev(volatilityValues) ?? 0);
  const highVolatilityPeriods = selectedSeries.filter((_, index) => (volatility[index] ?? 0) >= highVolatilityThreshold);
  const seasonalityStrength = Math.max(strengthFromRows(dayRows), strengthFromRows(monthRows));
  const evidencePayload = {
    artifactType: "time_series_profile",
    dataset: bundle?.dataset,
    mapping,
    selectedEntity,
    dateRange,
    rollingWindow,
    anomalySensitivity: sensitivity,
    diagnostics: {
      observationCount: selectedSeries.length,
      dateRange: `${selectedSeries[0]?.label ?? "-"} to ${selectedSeries[selectedSeries.length - 1]?.label ?? "-"}`,
      meanTarget: mean(values),
      trendDirection: trendDirection(selectedSeries),
      seasonalityStrength,
      lagSignal: candidateLags.length ? `Candidate lags ${candidateLags.join(", ")}` : "No strong lag signal in visible history",
      volatilityStatus: highVolatilityPeriods.length ? `${highVolatilityPeriods.length} high-volatility periods` : "Stable within visible range",
      anomalyCount: anomalies.length,
      anomalyMethod: "Rolling z-score",
      anomalyThreshold: sensitivityThreshold[sensitivity],
      profileScope: profile?.profileScope,
      profileScopeKind: profile?.profileScopeKind,
    },
  };

  async function handleNext() {
    const capturedAt = new Date().toISOString();
    await saveEvidenceToDatabase(projectId, {
      evidenceId: `time_series_profile_${projectId}`,
      evidenceType: "diagnostic",
      artifactType: "time_series_profile",
      title: "Time Series Profile Diagnostics",
      summary: `Profiled ${selectedSeries.length} periods for ${selectedEntity} using ${mapping?.dateColumn ?? "date"} and ${mapping?.targetColumn ?? "target"}.`,
      sourcePage: "Time Series Profile",
      sourceRoute: currentStep.route,
      datasetIds: bundle?.dataset?.datasetId ? [bundle.dataset.datasetId] : [],
      modelIds: [],
      documentIds: [],
      notebookIds: [],
      supportsSections: ["Time Series Profile", "Data Quality", "Model Design", "Monitoring Recommendations"],
      tags: ["time_series_forecasting", "time_series_profile", "rolling_mean", "seasonality", "autocorrelation", "anomaly"],
      status: "ready",
      importance: "high",
      capturedAt,
      workflowStep: currentStep.id,
      payload: evidencePayload,
      lineage: { datasetId: bundle?.dataset?.datasetId, versionId: bundle?.dataset?.versionId, profileScope: profile?.profileScopeKind },
    });
    logDecision({
      workflowStep: "Time Series Profile",
      actionType: "workflow_setting_changed",
      subject: "Time series profile diagnostics",
      previousValue: "Not captured",
      newValue: evidencePayload,
      systemRecommendation: "Use trend, seasonality, volatility, lag, and anomaly diagnostics to guide feature/calendar and backtest design.",
      followStatus: "followed",
    });
    markWorkflowStepComplete(currentStep.id);
    setWorkflowStepStatus(nextStep.id, "in_progress");
    setCurrentStepId(nextStep.id);
    await saveProjectToDatabase(snapshotFromStore());
    saveActiveProjectBeforeNavigation(useWorkflowStore.getState());
    navigate(nextStep.route);
    window.requestAnimationFrame(() => window.scrollTo({ top: 0, left: 0, behavior: "auto" }));
    return false;
  }

  const hasSeries = selectedSeries.length > 0;

  return (
    <StepShell
      title="Time Series Profile"
      subtitle="Compute trend, seasonality, volatility, autocorrelation, and anomaly diagnostics from the confirmed time-series input bundle."
      eyebrow="TIME SERIES & FORECASTING WORKFLOW"
      variant="analysis"
      nextLabel="Save Time Series Profile and Continue"
      nextDisabled={!hasSeries}
      nextDisabledReason="Confirm Time Series Data Acquisition before profiling."
      nextStatusLine="Persist time_series_profile evidence with dynamic diagnostic results."
      onNextClick={handleNext}
    >
      <div className="space-y-5">
        {!bundle ? (
          <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-900">
            Confirm Data Acquisition first. The Time Series Profile page requires the selected dataset mapping and input bundle.
          </section>
        ) : null}

        <section className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 text-white shadow-xl">
          <div className="p-6">
            <div className="text-xs font-semibold uppercase tracking-wide text-cyan-200">Dataset-driven diagnostics</div>
            <h1 className="mt-2 text-3xl font-semibold">Trend, Seasonality, Volatility, Lag, and Anomaly Profile</h1>
            <p className="mt-3 max-w-4xl text-sm leading-6 text-slate-200">
              Source: {bundle?.dataset?.name ?? "No confirmed dataset"} | Date: {mapping?.dateColumn ?? "-"} | Target: {mapping?.targetColumn ?? "-"} | Entity grain: {mapping?.entityColumns?.join(" + ") || "Aggregate"} | Frequency: {mapping?.aggregationFrequency ?? "-"} | Aggregation: {mapping?.aggregationMethod ?? "-"}
            </p>
          </div>
          <div className="grid border-t border-white/10 bg-white/5 md:grid-cols-4">
            {[
              ["Profile scope", profile?.profileScope ?? "Not loaded"],
              ["Visible periods", formatNumber(selectedSeries.length, 0)],
              ["Selected view", selectedEntity],
              ["Date range", `${selectedSeries[0]?.label ?? "-"} to ${selectedSeries[selectedSeries.length - 1]?.label ?? "-"}`],
            ].map(([label, value]) => (
              <div key={label} className="p-4"><div className="text-xs uppercase text-slate-400">{label}</div><div className="font-semibold">{value}</div></div>
            ))}
          </div>
        </section>

        <section className="rounded-2xl border border-blue-200 bg-blue-50 p-5 shadow-sm">
          <div className="grid gap-3 md:grid-cols-4">
            <label className="text-sm font-semibold text-slate-800">View
              <select className="mt-1 w-full rounded-lg border border-blue-200 bg-white px-3 py-2" value={selectedEntity} onChange={(event) => setSelectedEntity(event.target.value)}>
                {entityOptions.map((option) => <option key={option}>{option}</option>)}
              </select>
            </label>
            <label className="text-sm font-semibold text-slate-800">Date range
              <select className="mt-1 w-full rounded-lg border border-blue-200 bg-white px-3 py-2" value={dateRange} onChange={(event) => setDateRange(event.target.value)}>
                {["Full history", "Last 12 periods", "Last 24 periods", "Last 52 periods"].map((option) => <option key={option}>{option}</option>)}
              </select>
            </label>
            <label className="text-sm font-semibold text-slate-800">Rolling window
              <select className="mt-1 w-full rounded-lg border border-blue-200 bg-white px-3 py-2" value={rollingWindow} onChange={(event) => setRollingWindow(Number(event.target.value))}>
                {[3, 7, 14, 30].map((option) => <option key={option} value={option}>{option} periods</option>)}
              </select>
            </label>
            <label className="text-sm font-semibold text-slate-800">Anomaly sensitivity
              <select className="mt-1 w-full rounded-lg border border-blue-200 bg-white px-3 py-2" value={sensitivity} onChange={(event) => setSensitivity(event.target.value as keyof typeof sensitivityThreshold)}>
                {Object.keys(sensitivityThreshold).map((option) => <option key={option}>{option}</option>)}
              </select>
            </label>
          </div>
          <p className="mt-3 text-xs text-blue-800">These controls update the visible chart, rolling diagnostics, anomaly table, seasonality summaries, and evidence payload.</p>
        </section>

        {engineMessage ? <section className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">{engineMessage}</section> : null}
        {engineResult ? <section className="grid gap-4 xl:grid-cols-2"><AnalyticalResultCard title="Governed analytical profile" tone="emerald"><div className="grid grid-cols-2 gap-3 text-sm">{Object.entries(engineResult.statistics).slice(0, 8).map(([label, value]) => <div key={label} className="rounded-lg border border-emerald-100 bg-white p-2"><div className="text-[10px] uppercase tracking-wide text-slate-500">{label.replaceAll("_", " ")}</div><div className="mt-1 font-semibold text-slate-900">{String(value ?? "-")}</div></div>)}</div><div className="mt-3"><InterpretationPanel result={engineResult} /></div></AnalyticalResultCard>{engineResult.charts.slice(0, 1).map((item) => <AnalyticalChart key={item.chart_id} chart={item} />)}{engineResult.tables.slice(1, 3).map((item) => <AnalyticalResultCard key={item.table_id} title={item.title} tone="slate"><DiagnosticTable table={item} /></AnalyticalResultCard>)}</section> : null}

        {hasSeries ? <Chart points={selectedSeries} roll={rolling} anomalies={anomalies} /> : null}

        <section className="grid gap-4 xl:grid-cols-4">
          {[
            ["Observation count", formatNumber(selectedSeries.length, 0)],
            ["Mean target", formatNumber(mean(values))],
            ["Trend direction", trendDirection(selectedSeries)],
            ["Anomaly count", formatNumber(anomalies.length, 0)],
            ["Lag signal", candidateLags.length ? candidateLags.join(", ") : "Weak"],
            ["Volatility status", highVolatilityPeriods.length ? "Elevated" : "Stable"],
            ["Seasonality strength", seasonalityStrength >= 0.35 ? "Strong" : seasonalityStrength >= 0.15 ? "Moderate" : "Weak"],
            ["Profile basis", profile?.profileScopeKind === "full" ? "Full dataset" : profile?.profileScopeKind === "sampled" ? "Sampled profile" : "Preview profile"],
          ].map(([label, value]) => (
            <div key={label} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
              <div className="mt-1 text-lg font-semibold text-slate-950">{value}</div>
            </div>
          ))}
        </section>

        <section className="grid gap-4 xl:grid-cols-2">
          <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5 shadow-sm">
            <h3 className="text-base font-semibold text-slate-950">Rolling volatility diagnostics</h3>
            <p className="mt-1 text-sm text-emerald-900">Rolling standard deviation is computed over the selected rolling window. High-volatility periods exceed mean rolling volatility plus one standard deviation.</p>
            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              <div className="rounded-xl bg-white p-3"><div className="text-xs text-slate-500">Latest rolling std.</div><div className="text-lg font-semibold">{formatNumber(volatilityValues[volatilityValues.length - 1])}</div></div>
              <div className="rounded-xl bg-white p-3"><div className="text-xs text-slate-500">Volatility trend</div><div className="text-lg font-semibold">{trendDirection(volatilityValues.map((value, index) => ({ label: String(index), value })))}</div></div>
              <div className="rounded-xl bg-white p-3"><div className="text-xs text-slate-500">High-volatility periods</div><div className="text-lg font-semibold">{formatNumber(highVolatilityPeriods.length, 0)}</div></div>
            </div>
          </div>
          <div className="rounded-2xl border border-amber-200 bg-amber-50 p-5 shadow-sm">
            <h3 className="text-base font-semibold text-slate-950">Autocorrelation diagnostics</h3>
            <p className="mt-1 text-sm text-amber-900">{selectedSeries.length < 32 ? "Short-history warning: lag 30 is directional only until more periods are available." : "ACF uses the selected visible range."}</p>
            <div className="mt-4 space-y-2">
              {acfRows.map((row) => (
                <div key={row.lag} className="grid grid-cols-[70px_1fr_80px] items-center gap-3 text-sm">
                  <span className="font-semibold">Lag {row.lag}</span>
                  <div className="h-3 rounded-full bg-white"><div className="h-full rounded-full bg-blue-500" style={{ width: `${Math.max(2, Math.min(100, Math.abs(row.value ?? 0) * 100))}%` }} /></div>
                  <span className="text-right tabular-nums">{row.value === null ? "Too short" : formatNumber(row.value, 3)}</span>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="grid gap-4 xl:grid-cols-2">
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h3 className="text-base font-semibold text-slate-950">Seasonality diagnostics</h3>
            <p className="mt-1 text-sm text-slate-600">{selectedSeries.length < 14 ? "Short-history warning: day-of-week patterns need more periods for governed interpretation." : "Day-of-week pattern for daily data."}</p>
            <div className="mt-4"><BarRows rows={dayRows} label="Day" /></div>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h3 className="text-base font-semibold text-slate-950">Month-of-year pattern</h3>
            <p className="mt-1 text-sm text-slate-600">{selectedSeries.length < 180 ? "Short-history warning: month-of-year diagnostics are directional until enough history exists." : "Month-of-year seasonality view."}</p>
            <div className="mt-4"><BarRows rows={monthRows} label="Month" /></div>
          </div>
        </section>

        <section className="grid gap-4 xl:grid-cols-[1fr_1.3fr]">
          <div className="rounded-2xl border border-orange-200 bg-orange-50 p-5 shadow-sm">
            <h3 className="text-base font-semibold text-slate-950">Anomaly diagnostics</h3>
            <div className="mt-3 grid gap-3 sm:grid-cols-3">
              <div className="rounded-xl bg-white p-3"><div className="text-xs text-slate-500">Method</div><div className="font-semibold">Rolling z-score</div></div>
              <div className="rounded-xl bg-white p-3"><div className="text-xs text-slate-500">Threshold</div><div className="font-semibold">{sensitivityThreshold[sensitivity]} sigma</div></div>
              <div className="rounded-xl bg-white p-3"><div className="text-xs text-slate-500">Anomalies</div><div className="font-semibold">{formatNumber(anomalies.length, 0)}</div></div>
            </div>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h3 className="text-base font-semibold text-slate-950">Top anomalous periods</h3>
            <div className="mt-4 overflow-hidden rounded-xl border border-slate-200">
              <table className="w-full text-left text-sm">
                <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500"><tr><th className="px-3 py-2">Period</th><th className="px-3 py-2">Actual</th><th className="px-3 py-2">Rolling mean</th><th className="px-3 py-2">Z-score</th></tr></thead>
                <tbody className="divide-y divide-slate-100">
                  {anomalies.slice().sort((a, b) => b.zScore - a.zScore).slice(0, 8).map((point) => (
                    <tr key={point.label}><td className="px-3 py-2 font-semibold">{point.label}</td><td className="px-3 py-2">{formatNumber(point.value)}</td><td className="px-3 py-2">{formatNumber(point.rollingMean)}</td><td className="px-3 py-2">{formatNumber(point.zScore, 2)}</td></tr>
                  ))}
                  {!anomalies.length ? <tr><td className="px-3 py-4 text-slate-500" colSpan={4}>No anomalous periods exceed the selected threshold.</td></tr> : null}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="text-base font-semibold text-slate-950">Diagnostic summary table</h3>
          <div className="mt-4 overflow-hidden rounded-xl border border-slate-200">
            <table className="w-full text-left text-sm">
              <tbody className="divide-y divide-slate-100">
                {Object.entries(evidencePayload.diagnostics).map(([key, value]) => (
                  <tr key={key}><th className="w-72 bg-slate-50 px-3 py-2 text-xs uppercase tracking-wide text-slate-500">{key.replace(/([A-Z])/g, " $1")}</th><td className="px-3 py-2 text-slate-800">{typeof value === "number" ? formatNumber(value, 3) : String(value ?? "-")}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </StepShell>
  );
}
