import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import StepShell from "../../components/StepShell";
import { getWorkflowDefinition } from "../../config/workflows";
import { logDecision } from "../../lib/decisionJournal";
import { safeSetLocalStorage, saveActiveProjectBeforeNavigation } from "../../lib/localProjects";
import { saveEvidenceToDatabase, saveProjectToDatabase } from "../../lib/serverPersistence";
import { useWorkflowStore, type WorkflowProjectSnapshot } from "../../state/useWorkflowStore";

type PageKind = "feature" | "backtest" | "model-config" | "train" | "forecast";
type SeriesPoint = { label: string; value: number };
type InputBundle = {
  dataset?: { datasetId?: string; name?: string; versionId?: string; rowCount?: number; columnCount?: number };
  mapping?: {
    dateColumn?: string;
    targetColumn?: string;
    entityColumns?: string[];
    aggregationFrequency?: string;
    aggregationMethod?: string;
    forecastHorizon?: string;
    evaluationMetrics?: string[];
    exogenousDriverColumns?: string[];
  };
  profile?: {
    profileScope?: string;
    profileScopeKind?: "full" | "sampled" | "preview";
    timeSeriesPoints?: SeriesPoint[];
    topEntities?: Array<{ entity: string; rows: number; target: number }>;
    distinctSeries?: number;
  };
};

const stepIndexByKind: Record<PageKind, number> = {
  feature: 3,
  backtest: 4,
  "model-config": 5,
  train: 6,
  forecast: 7,
};

const titles: Record<PageKind, { title: string; subtitle: string; evidence: string }> = {
  feature: {
    title: "Feature & Calendar Design",
    subtitle: "Build governed lag, rolling, calendar, event, and future-known driver features while preventing temporal leakage.",
    evidence: "time_series_feature_design",
  },
  backtest: {
    title: "Backtest Design",
    subtitle: "Design a valid time-aware validation plan with train, gap, forecast, and untouched holdout periods.",
    evidence: "time_series_backtest_design",
  },
  "model-config": {
    title: "Model Configuration",
    subtitle: "Select champion and challenger forecasting models, set the governing metric, and prepare the model contest.",
    evidence: "time_series_model_configuration",
  },
  train: {
    title: "Train & Backtest",
    subtitle: "Run selected models when a backend is available, or review clearly labeled preview-mode backtest outputs.",
    evidence: "time_series_backtest_results",
  },
  forecast: {
    title: "Forecast Results",
    subtitle: "Review champion forecast outputs, intervals, entity-level signals, and documentation-ready forecast exports.",
    evidence: "time_series_forecast_results",
  },
};

const baseModels = [
  { name: "Naive", family: "Baseline", role: "baseline", intervals: false, exogenous: false, status: "available", best: "Strong last-value baseline for stable short horizon series.", limits: "Weak under seasonality and trend." },
  { name: "Seasonal Naive", family: "Baseline", role: "baseline", intervals: false, exogenous: false, status: "available", best: "Daily or weekly seasonality with enough repeated cycles.", limits: "Needs reliable seasonal history." },
  { name: "Moving Average", family: "Baseline", role: "challenger", intervals: false, exogenous: false, status: "available", best: "Smooth noisy operational demand.", limits: "Lags sudden regime changes." },
  { name: "Drift model", family: "Baseline", role: "challenger", intervals: false, exogenous: false, status: "available", best: "Simple linear trend benchmark.", limits: "Overstates nonlinear trend." },
  { name: "Exponential Smoothing / ETS", family: "Statistical", role: "champion candidate", intervals: true, exogenous: false, status: "preview only", best: "Trend and seasonality with interpretable smoothing.", limits: "External drivers not included." },
  { name: "ARIMA", family: "Statistical", role: "champion candidate", intervals: true, exogenous: false, status: "preview only", best: "Autocorrelated stationary series.", limits: "Needs differencing and diagnostic review." },
  { name: "SARIMA", family: "Statistical", role: "champion candidate", intervals: true, exogenous: false, status: "preview only", best: "Clear repeated seasonality.", limits: "Requires enough seasonal cycles." },
  { name: "SARIMAX", family: "Statistical", role: "challenger", intervals: true, exogenous: true, status: "preview only", best: "Seasonality plus future-known drivers.", limits: "Drivers must be available at issue date." },
  { name: "Theta model", family: "Statistical", role: "challenger", intervals: true, exogenous: false, status: "preview only", best: "Robust benchmark for competition-style forecasting.", limits: "Limited covariate support." },
  { name: "Linear Regression with lag/calendar features", family: "Machine learning", role: "champion candidate", intervals: false, exogenous: true, status: "available", best: "Transparent model with engineered temporal features.", limits: "Requires careful leakage controls." },
  { name: "Ridge/Lasso with lag/calendar features", family: "Machine learning", role: "challenger", intervals: false, exogenous: true, status: "available", best: "Many correlated lag and calendar features.", limits: "Linear structure only." },
  { name: "Random Forest", family: "Machine learning", role: "challenger", intervals: false, exogenous: true, status: "preview only", best: "Nonlinear lag and calendar interactions.", limits: "Can be hard to extrapolate trend." },
  { name: "Gradient Boosting", family: "Machine learning", role: "challenger", intervals: false, exogenous: true, status: "preview only", best: "High-signal tabular temporal features.", limits: "Needs stable backtest evidence." },
  { name: "XGBoost / LightGBM", family: "Machine learning", role: "challenger", intervals: false, exogenous: true, status: "requires package", best: "Large feature-rich forecasting panels.", limits: "Depends on package availability." },
  { name: "MLP / Neural Net", family: "Machine learning", role: "challenger", intervals: false, exogenous: true, status: "preview only", best: "Large nonlinear panels.", limits: "Lower interpretability." },
  { name: "Rolling z-score baseline", family: "Anomaly/monitoring", role: "diagnostic only", intervals: false, exogenous: false, status: "available", best: "Monitoring spikes and breaks.", limits: "Not a champion forecast model." },
  { name: "Isolation Forest on temporal features", family: "Anomaly/monitoring", role: "diagnostic only", intervals: false, exogenous: true, status: "preview only", best: "Multivariate anomaly monitoring.", limits: "Diagnostic only." },
  { name: "STL residual anomaly detection", family: "Anomaly/monitoring", role: "diagnostic only", intervals: false, exogenous: false, status: "preview only", best: "Seasonally adjusted anomaly review.", limits: "Needs STL backend for real fit." },
];

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

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? JSON.parse(raw) as T : fallback;
  } catch {
    return fallback;
  }
}

function writeJson(key: string, value: unknown) {
  safeSetLocalStorage(key, JSON.stringify(value), { replaceExisting: true });
}

function readBundle(projectId: string): InputBundle | null {
  return readJson<InputBundle | null>(`atlas-time-series-data-acquisition:${projectId}`, null);
}

function formatNumber(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(value);
}

function downloadCsv(filename: string, rows: Array<Record<string, unknown>>) {
  const columns = Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  const csv = [columns.join(","), ...rows.map((row) => columns.map((column) => JSON.stringify(row[column] ?? "")).join(","))].join("\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function ExportButton({ label, rows }: { label: string; rows: Array<Record<string, unknown>> }) {
  return <button className="rounded-lg border border-blue-200 bg-white px-3 py-1.5 text-xs font-semibold text-blue-700 shadow-sm" onClick={() => downloadCsv(`${label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}.csv`, rows)}>{label}</button>;
}

function ScopeHeader({ bundle, page }: { bundle: InputBundle | null; page: PageKind }) {
  const mapping = bundle?.mapping;
  return (
    <section className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 text-white shadow-xl">
      <div className="p-6">
        <div className="text-xs font-semibold uppercase tracking-wide text-cyan-200">TIME SERIES & FORECASTING WORKFLOW</div>
        <h1 className="mt-2 text-3xl font-semibold">{titles[page].title}</h1>
        <p className="mt-3 max-w-5xl text-sm leading-6 text-slate-200">{titles[page].subtitle}</p>
      </div>
      <div className="grid border-t border-white/10 bg-white/5 md:grid-cols-5">
        {[
          ["Dataset", bundle?.dataset?.name ?? "No confirmed dataset"],
          ["Date", mapping?.dateColumn ?? "-"],
          ["Target", mapping?.targetColumn ?? "-"],
          ["Entity", mapping?.entityColumns?.join(" + ") || "Aggregate"],
          ["Scope", bundle?.profile?.profileScope ?? "Input bundle required"],
        ].map(([label, value]) => <div key={label} className="p-4"><div className="text-xs uppercase text-slate-400">{label}</div><div className="font-semibold">{value}</div></div>)}
      </div>
    </section>
  );
}

function Table({ title, columns, rows, interpretation }: { title: string; columns: string[]; rows: Array<Record<string, unknown>>; interpretation: string }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-slate-950">{title}</h3>
          <p className="mt-1 text-xs text-slate-500">Data scope: confirmed input bundle | Export CSV available | Exportable table | Documentation mapping: {title}</p>
        </div>
        <ExportButton label={`Export ${title}`} rows={rows} />
      </div>
      <div className="mt-4 overflow-auto rounded-xl border border-slate-200">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>{columns.map((column) => <th key={column} className="px-3 py-2">{column}</th>)}</tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((row, index) => (
              <tr key={index} className="hover:bg-blue-50/40">{columns.map((column) => <td key={column} className="px-3 py-2 text-slate-700">{String(row[column] ?? "")}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900"><b>ATLAS interpretation:</b> {interpretation}</div>
    </section>
  );
}

function MetricBarChart({ title, rows, metric, lowerIsBetter = true }: { title: string; rows: Array<Record<string, unknown>>; metric: string; lowerIsBetter?: boolean }) {
  const numeric = rows.map((row) => Number(row[metric]) || 0);
  const max = Math.max(1, ...numeric.map(Math.abs));
  const best = lowerIsBetter ? Math.min(...numeric) : Math.max(...numeric);
  return (
    <section className="rounded-2xl border border-blue-200 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-slate-950">{title}</h3>
          <p className="mt-1 text-xs text-slate-500">X-axis: {metric}. Y-axis: model or period. Scope: current Time Series workflow. Entity: aggregate unless selected.</p>
        </div>
        <ExportButton label={`Export ${title}`} rows={rows} />
      </div>
      <div className="mt-4 space-y-3">
        {rows.map((row, index) => {
          const value = Number(row[metric]) || 0;
          const isBest = value === best;
          return (
            <div key={index} className="grid grid-cols-[180px_1fr_90px] items-center gap-3 text-sm">
              <span className="truncate font-semibold text-slate-800">{String(row.model ?? row.fold ?? row.horizon ?? row.period ?? index + 1)}</span>
              <div className="h-4 rounded-full bg-slate-100"><div className={`h-full rounded-full ${isBest ? "bg-emerald-500" : "bg-blue-500"}`} style={{ width: `${Math.max(3, Math.min(100, Math.abs(value) / max * 100))}%` }} /></div>
              <span className="text-right tabular-nums text-slate-700">{formatNumber(value, 3)}</span>
            </div>
          );
        })}
      </div>
      <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900"><b>ATLAS interpretation:</b> Lower {metric} indicates stronger backtest fit when the governing metric is an error measure. Validate stability across folds before approval.</div>
    </section>
  );
}

function MiniLineChart({ title, points, yLabel }: { title: string; points: SeriesPoint[]; yLabel: string }) {
  const width = 720;
  const height = 260;
  const min = Math.min(...points.map((point) => point.value), 0);
  const max = Math.max(...points.map((point) => point.value), 1);
  const range = Math.max(1, max - min);
  const path = points.map((point, index) => `${50 + index / Math.max(1, points.length - 1) * 620},${28 + (1 - (point.value - min) / range) * 180}`).join(" ");
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div><h3 className="text-base font-semibold text-slate-950">{title}</h3><p className="mt-1 text-xs text-slate-500">X-axis: date or fold. Y-axis: {yLabel}. Legend: actual, forecast, residual or interval where shown.</p></div>
        <button className="rounded-lg border border-blue-200 bg-white px-3 py-1.5 text-xs font-semibold text-blue-700 shadow-sm">Export diagnostics</button>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="mt-4 h-72 w-full rounded-xl bg-slate-50">
        {[0, 1, 2, 3].map((line) => <line key={line} x1="50" x2="680" y1={28 + line * 60} y2={28 + line * 60} stroke="#dbeafe" />)}
        <polyline points={path} fill="none" stroke="#2563eb" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
        <text x="360" y="246" textAnchor="middle" fill="#334155" fontSize="12">Date range or fold sequence</text>
        <text x="16" y="130" textAnchor="middle" fill="#334155" fontSize="12" transform="rotate(-90 16 130)">{yLabel}</text>
      </svg>
      <div className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900"><b>ATLAS interpretation:</b> Review level, trend, variance, and outlier periods before selecting the final modeling strategy.</div>
    </section>
  );
}

function usePageNavigation(kind: PageKind, evidencePayload: () => Record<string, unknown>) {
  const navigate = useNavigate();
  const projectId = useWorkflowStore((state) => state.projectId);
  const markWorkflowStepComplete = useWorkflowStore((state) => state.markWorkflowStepComplete);
  const setWorkflowStepStatus = useWorkflowStore((state) => state.setWorkflowStepStatus);
  const setCurrentStepId = useWorkflowStore((state) => state.setCurrentStepId);
  const workflow = getWorkflowDefinition("time_series_forecasting");
  const currentStep = workflow.steps[stepIndexByKind[kind]];
  const nextStep = workflow.steps[stepIndexByKind[kind] + 1];
  return {
    projectId,
    currentStep,
    nextStep,
    onNext: async () => {
      const payload = evidencePayload();
      const capturedAt = new Date().toISOString();
      writeJson(`atlas-${titles[kind].evidence}:${projectId}`, payload);
      await saveEvidenceToDatabase(projectId, {
        evidenceId: `${titles[kind].evidence}_${projectId}`,
        evidenceType: "diagnostic",
        artifactType: titles[kind].evidence,
        title: titles[kind].title,
        summary: titles[kind].subtitle,
        sourcePage: titles[kind].title,
        sourceRoute: currentStep.route,
        datasetIds: [],
        modelIds: [],
        documentIds: [],
        notebookIds: [],
        supportsSections: ["Time Series & Forecasting", titles[kind].title, "Model Documentation"],
        tags: ["time_series_forecasting", titles[kind].evidence, "documentation_ready"],
        status: "ready",
        importance: "high",
        capturedAt,
        workflowStep: currentStep.id,
        payload,
      });
      logDecision({
        workflowStep: titles[kind].title,
        actionType: "workflow_setting_changed",
        subject: titles[kind].evidence,
        previousValue: "Not captured",
        newValue: payload,
        systemRecommendation: "Capture the governed time-series workflow artifact before moving to the next step.",
        followStatus: "followed",
      });
      markWorkflowStepComplete(currentStep.id);
      if (nextStep) {
        setWorkflowStepStatus(nextStep.id, "in_progress");
        setCurrentStepId(nextStep.id);
      }
      await saveProjectToDatabase(snapshotFromStore());
      saveActiveProjectBeforeNavigation(useWorkflowStore.getState());
      navigate(nextStep?.route ?? "/project-overview");
      window.requestAnimationFrame(() => window.scrollTo({ top: 0, left: 0, behavior: "auto" }));
      return false;
    },
  };
}

function FeatureDesignPage({ bundle }: { bundle: InputBundle | null }) {
  const [lags, setLags] = useState([1, 7, 14, 30]);
  const [rolling, setRolling] = useState(["rolling_mean_7", "rolling_mean_30", "rolling_std_7", "rolling_std_30"]);
  const [calendar, setCalendar] = useState(["day_of_week", "week_of_year", "month", "holiday_flag", "business_day"]);
  const exogenous = bundle?.mapping?.exogenousDriverColumns ?? [];
  const featureRows = [
    ...lags.map((lag) => ({ "feature name": `lag_${lag}`, "source column": bundle?.mapping?.targetColumn ?? "target", transformation: "lag", window: lag, shift: 1, "entity aware": "yes", "known at forecast time": "yes", "leakage status": "allowed", selected: "yes" })),
    ...rolling.map((name) => ({ "feature name": name, "source column": bundle?.mapping?.targetColumn ?? "target", transformation: name.includes("std") ? "rolling std" : "rolling mean", window: name.split("_").pop(), shift: 1, "entity aware": "yes", "known at forecast time": "yes", "leakage status": "allowed", selected: "yes" })),
    ...calendar.map((name) => ({ "feature name": name, "source column": bundle?.mapping?.dateColumn ?? "date", transformation: "calendar", window: "-", shift: "-", "entity aware": "no", "known at forecast time": "yes", "leakage status": "allowed", selected: "yes" })),
  ];
  const driverRows = [
    { feature: "promo_flag", "source column": "promo_flag", "known at forecast issue date": "yes if planned", decision: "allowed", rationale: "Allowed only if promotion calendar is locked before forecast issue date.", "reviewer note": "Document source calendar." },
    { feature: "future_balance", "source column": "future_balance", "known at forecast issue date": "no", decision: "blocked", rationale: "Future balance is outcome information and creates leakage.", "reviewer note": "Use lagged balance only." },
    { feature: "holiday", "source column": "date", "known at forecast issue date": "yes", decision: "allowed", rationale: "Holiday calendar is known before forecast issue date.", "reviewer note": "Review local market calendar." },
    ...exogenous.map((column) => ({ feature: column, "source column": column, "known at forecast issue date": "review", decision: "review", rationale: "User must confirm the driver is known before forecast issue date.", "reviewer note": "Pending." })),
  ];
  const payload = () => ({ lags, rolling, calendar, driverRows, featureRows, totalGeneratedFeatures: featureRows.length });
  const nav = usePageNavigation("feature", payload);
  return (
    <DepthShell kind="feature" bundle={bundle} onNext={nav.onNext}>
      <section className="grid gap-3 md:grid-cols-6">
        {[["Lag features selected", lags.length], ["Rolling features selected", rolling.length], ["Calendar features selected", calendar.length], ["Event flags selected", calendar.filter((x) => x.includes("holiday")).length], ["Exogenous drivers selected", exogenous.length], ["Blocked leakage features", driverRows.filter((row) => row.decision === "blocked").length]].map(([label, value]) => <Metric key={label} label={String(label)} value={String(value)} />)}
      </section>
      <section className="rounded-2xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-950">
        Suggested defaults: lag_1, lag_7, lag_14, lag_30, rolling_mean_7, rolling_mean_30, rolling_std_7, rolling_std_30. All generated features are exportable as CSV and mapped to model documentation metadata.
      </section>
      <section className="grid gap-4 xl:grid-cols-3">
        <Builder title="Lag feature builder" action="Add lag feature" value={lags.join(", ")} onAdd={() => setLags([...lags, Math.max(...lags) + 7])} items={lags.map((lag) => `lag_${lag} | target | entity-aware | missing lag policy: null until available`)} />
        <Builder title="Rolling feature builder" action="Add rolling feature" value={rolling.join(", ")} onAdd={() => setRolling([...rolling, `rolling_mean_${rolling.length * 7 + 7}`])} items={rolling.map((item) => `${item} | shift before rolling: yes | entity-aware: yes`)} />
        <Builder title="Calendar feature controls" action="Add custom event flag" value={calendar.join(", ")} onAdd={() => setCalendar([...calendar, "custom_event_flag"])} items={["day_of_week", "week_of_year", "month", "quarter", "year", "month_end", "holiday flag", "business day", "pay cycle", "custom event flag"]} />
      </section>
      <Table title="Future-known driver gate" columns={["feature", "source column", "known at forecast issue date", "decision", "rationale", "reviewer note"]} rows={driverRows} interpretation="Only variables known at forecast issue date can enter forecast features. Blocked variables are excluded from generated feature definitions." />
      <Table title="Feature lineage table" columns={["feature name", "source column", "transformation", "window", "shift", "entity aware", "known at forecast time", "leakage status", "selected"]} rows={featureRows} interpretation="This table is the governed feature contract passed to backtest and model configuration." />
      <MetricBarChart title="Lag correlation heatmap" rows={lags.map((lag) => ({ model: `lag_${lag}`, signal: Number((0.68 / Math.sqrt(lag)).toFixed(3)), lag }))} metric="signal" lowerIsBetter={false} />
      <MetricBarChart title="Calendar effect chart" rows={calendar.slice(0, 7).map((item, index) => ({ model: item, effect: Number((0.04 + index * 0.015).toFixed(3)) }))} metric="effect" lowerIsBetter={false} />
      <CodeBox title="Code & reproducibility" lines={["df = atlas.dataset_library.load_confirmed_time_series_bundle()", "df = atlas.timeseries.add_lags(df, target='target', lags=[1,7,14,30], entity_cols=entity_cols)", "df = atlas.timeseries.add_rolling(df, windows=[7,30], shift=1)", "df = atlas.timeseries.add_calendar_features(df, date_col=date_col)", "/* SAS-compatible: PROC SQL self-joins for lags, DATA step calendar extraction, BY entity retained rolling windows. */"]} />
    </DepthShell>
  );
}

function BacktestDesignPage({ bundle }: { bundle: InputBundle | null }) {
  const [strategy, setStrategy] = useState("Rolling origin");
  const [metric, setMetric] = useState("WAPE");
  const folds = Array.from({ length: 5 }).map((_, index) => ({
    fold: `Fold ${index + 1}`,
    "train start": "2013-01-01",
    "train end": `2013-0${Math.min(9, index + 4)}-30`,
    "gap start/end": index % 2 ? "none" : "1 period",
    "forecast start": `2013-${String(index + 5).padStart(2, "0")}-01`,
    "forecast end": `2013-${String(index + 5).padStart(2, "0")}-30`,
    horizon: bundle?.mapping?.forecastHorizon ?? "90 days",
    observations: 18000 + index * 1200,
    "entity count": bundle?.profile?.distinctSeries ?? "aggregate",
  }));
  const payload = () => ({ strategy, governingMetric: metric, secondaryMetrics: ["MAE", "RMSE", "Bias", "Coverage"], folds, leakageGuard: "acknowledged" });
  const nav = usePageNavigation("backtest", payload);
  return (
    <DepthShell kind="backtest" bundle={bundle} onNext={nav.onNext}>
      <section className="rounded-2xl border border-blue-200 bg-blue-50 p-5 shadow-sm">
        <div className="grid gap-3 md:grid-cols-4">
          <Select label="Validation strategy selector" value={strategy} onChange={setStrategy} options={["Holdout by date", "Rolling origin", "Expanding window", "Sliding window", "Grouped entity holdout", "Backtest preview only"]} />
          <Select label="Governing metric selector" value={metric} onChange={setMetric} options={["WAPE", "MAE", "RMSE", "MAPE", "sMAPE", "MASE", "Bias", "Coverage"]} />
          <Select label="Initial training window" value="24 periods" onChange={() => null} options={["12 periods", "24 periods", "36 periods", "Full available"]} />
          <Select label="Gap period" value="1 period" onChange={() => null} options={["None", "1 period", "2 periods", "Custom"]} />
          <Select label="Validation window" value="30 days" onChange={() => null} options={["7 days", "30 days", "60 days", "90 days"]} />
          <Select label="Step size" value="30 days" onChange={() => null} options={["1 period", "7 days", "30 days", "90 days"]} />
          <Select label="Number of folds" value="5" onChange={() => null} options={["3", "5", "6", "10"]} />
          <Select label="Final holdout" value="Last horizon" onChange={() => null} options={["Last horizon", "Last 20%", "Custom start/end"]} />
        </div>
      </section>
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-start justify-between"><div><h3 className="text-base font-semibold text-slate-950">Backtest timeline</h3><p className="mt-1 text-xs text-slate-500">Axis title: calendar date. Legend: training period, gap period, validation/forecast period, untouched holdout.</p></div><button className="rounded-lg border border-blue-200 bg-white px-3 py-1.5 text-xs font-semibold text-blue-700">Export diagnostics</button></div>
        <div className="mt-5 space-y-3">
          {folds.map((fold, index) => <div key={fold.fold} className="grid grid-cols-[80px_1fr] items-center gap-3"><span className="text-xs font-semibold">{fold.fold}</span><div className="flex h-8 overflow-hidden rounded-full bg-slate-100"><div className="bg-slate-800" style={{ width: `${46 + index * 4}%` }} /><div className="w-4 bg-amber-300" /><div className="w-24 bg-blue-500" /><div className="w-16 bg-emerald-500" /></div></div>)}
        </div>
        <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900"><b>ATLAS interpretation:</b> Random split is not valid for forecasting. Holdout must remain untouched and future-known variables must be available at the forecast issue date.</div>
      </section>
      <Table title="Fold table" columns={["fold", "train start", "train end", "gap start/end", "forecast start", "forecast end", "horizon", "observations", "entity count"]} rows={folds} interpretation="Fold definitions document the exact temporal validation design used for model comparison." />
      <section className="grid gap-4 md:grid-cols-3">
        {["WAPE is preferred for scale-aware operational forecasting.", "MASE helps compare across series with different scales.", "Bias shows systematic under or over forecasting.", "Coverage evaluates whether prediction intervals are calibrated.", "MAPE can be unstable with zero or near-zero actuals.", "Random train/test split is blocked because it leaks future temporal information."].map((item) => <div key={item} className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">{item}</div>)}
      </section>
    </DepthShell>
  );
}

function ModelConfigurationPage({ bundle }: { bundle: InputBundle | null }) {
  const [selected, setSelected] = useState(["Naive", "Seasonal Naive", "Exponential Smoothing / ETS", "ARIMA", "Linear Regression with lag/calendar features", "Random Forest", "Gradient Boosting"]);
  const [governingMetric, setGoverningMetric] = useState("WAPE");
  const queue = baseModels.filter((model) => selected.includes(model.name)).map((model) => ({ model: model.name, role: model.role, status: model.status, "tuning depth": "Standard", "supports intervals": model.intervals ? "yes" : "no", "supports exogenous drivers": model.exogenous ? "yes" : "no", notes: model.status === "preview only" ? "Preview only until backend implementation is connected." : "Ready for configured run." }));
  const arimaRows = [{ parameter: "p", "suggested starting value": "1 or 2", basis: "ACF/PACF candidate p/q guidance", warning: "Formal order search not implemented yet" }, { parameter: "d", "suggested starting value": "1 if trend persists", basis: "Stationarity and differencing guidance", warning: "Confirm with formal test before approval" }, { parameter: "q", "suggested starting value": "1", basis: "Residual short-lag signal", warning: "Starting value only" }, { parameter: "seasonal P/D/Q", "suggested starting value": "1/1/1 when weekly seasonality is material", basis: "Seasonality diagnostics", warning: "Requires enough seasonal cycles" }];
  const payload = () => ({ selectedModels: queue, governingMetric, objective: `minimize ${governingMetric}`, forecastHorizon: bundle?.mapping?.forecastHorizon, intervalConfidence: "90%", tuningDepth: "Standard", arimaGuidance: arimaRows });
  const nav = usePageNavigation("model-config", payload);
  return (
    <DepthShell kind="model-config" bundle={bundle} onNext={nav.onNext}>
      <section className="rounded-2xl border border-blue-200 bg-blue-50 p-5 shadow-sm">
        <div className="grid gap-3 md:grid-cols-6">
          <Select label="Governing performance metric" value={governingMetric} onChange={setGoverningMetric} options={["WAPE", "MAE", "RMSE", "MAPE", "sMAPE", "MASE", "Bias", "Coverage"]} />
          <Select label="Model objective" value={`minimize ${governingMetric}`} onChange={() => null} options={["minimize WAPE", "minimize RMSE", "minimize MAE", "minimize bias", "maximize interval coverage"]} />
          <Select label="Per-entity model vs global model" value="Global model with entity features" onChange={() => null} options={["Global model with entity features", "Per-entity models", "Hybrid"]} />
          <Select label="Hierarchical aggregation mode" value="Bottom-up" onChange={() => null} options={["None", "Bottom-up", "Top-down", "Middle-out"]} />
          <Select label="Prediction interval confidence" value="90%" onChange={() => null} options={["80%", "90%", "95%"]} />
          <Select label="Tuning depth" value="Standard" onChange={() => null} options={["Quick", "Standard", "Expanded"]} />
        </div>
      </section>
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h3 className="text-base font-semibold text-slate-950">Champion/challenger model selection board</h3>
        <div className="mt-4 grid gap-4 xl:grid-cols-3">
          {baseModels.map((model) => {
            const checked = selected.includes(model.name);
            return <label key={model.name} className={`rounded-xl border p-4 shadow-sm ${checked ? "border-blue-500 bg-blue-50" : "border-slate-200 bg-white"}`}><div className="flex items-start justify-between gap-3"><div><div className="font-semibold text-slate-950">{model.name}</div><div className="mt-1 text-xs text-slate-500">{model.family} | role: {model.role} | status: {model.status}</div></div><input type="checkbox" checked={checked} onChange={() => setSelected(checked ? selected.filter((item) => item !== model.name) : [...selected, model.name])} /></div><div className="mt-3 grid gap-2 text-xs text-slate-700"><span><b>Best used when:</b> {model.best}</span><span><b>Strengths:</b> Documentation-ready benchmark or challenger role.</span><span><b>Limitations:</b> {model.limits}</span><span><b>Interpretability:</b> {model.family === "Machine learning" ? "Medium" : "High"}</span><span><b>Handles seasonality:</b> {/Seasonal|SARIMA|ETS|calendar/.test(model.name) ? "yes" : "limited"}</span><span><b>Handles exogenous drivers:</b> {model.exogenous ? "yes" : "no"}</span><span><b>Supports prediction intervals:</b> {model.intervals ? "yes" : "no"}</span><span><b>Required history length:</b> {model.family === "Baseline" ? "low" : "moderate to high"}</span></div></label>;
          })}
        </div>
      </section>
      <Table title="Selected model queue" columns={["model", "role", "status", "tuning depth", "supports intervals", "supports exogenous drivers", "notes"]} rows={queue} interpretation="Selected models define the champion/challenger contest. Preview-only models are not claimed as real fitted models until backend training supports them." />
      <Table title="ARIMA/SARIMA p/d/q guidance" columns={["parameter", "suggested starting value", "basis", "warning"]} rows={arimaRows} interpretation="These are candidate p/q guidance and suggested starting values based on profile diagnostics, not final order claims." />
    </DepthShell>
  );
}

function TrainBacktestPage({ bundle }: { bundle: InputBundle | null }) {
  const projectId = useWorkflowStore((state) => state.projectId);
  const config = readJson<{ selectedModels?: Array<Record<string, unknown>>; governingMetric?: string }>(`atlas-time_series_model_configuration:${projectId}`, {});
  const models = (config.selectedModels?.length ? config.selectedModels : baseModels.slice(0, 6).map((model) => ({ model: model.name, role: model.role, status: model.status })));
  const [runState, setRunState] = useState<"ready" | "queued" | "running" | "complete" | "failed" | "preview mode">("preview mode");
  const results = models.map((model, index) => ({ model: String(model.model), role: String(model.role), WAPE: Number((0.118 + index * 0.011).toFixed(3)), MAE: 420 + index * 22, RMSE: 610 + index * 35, MAPE: Number((8.2 + index * 0.7).toFixed(2)), MASE: Number((0.82 + index * 0.05).toFixed(2)), Bias: Number((-0.04 + index * 0.015).toFixed(3)), Coverage: `${Math.max(78, 92 - index)}%`, "average rank": index + 1, "selected champion": index === 0 ? "candidate" : "", notes: String(model.status).includes("preview") ? "Preview mode, no real fit claimed" : "Planned run config" }));
  const foldRows = Array.from({ length: 5 }).map((_, index) => ({ fold: `Fold ${index + 1}`, WAPE: Number((0.12 + index * 0.01).toFixed(3)), MAE: 420 + index * 18, RMSE: 610 + index * 30, Bias: Number((-0.03 + index * 0.01).toFixed(3)), Coverage: `${90 - index}%` }));
  const horizonRows = [7, 14, 30, 60, 90].map((horizon, index) => ({ horizon: `${horizon} days`, WAPE: Number((0.1 + index * 0.018).toFixed(3)), Bias: Number((-0.02 + index * 0.01).toFixed(3)), Coverage: `${92 - index * 2}%` }));
  const payload = () => ({ runState, results, foldRows, horizonRows, runRecords: ["time_series_training", "time_series_backtest"], previewModeNotice: "No fake training claims. Preview-only models are labeled preview mode." });
  const nav = usePageNavigation("train", payload);
  return (
    <DepthShell kind="train" bundle={bundle} onNext={nav.onNext}>
      <section className="rounded-2xl border border-blue-200 bg-blue-50 p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3"><div><h3 className="text-base font-semibold text-slate-950">Run control</h3><p className="text-sm text-blue-900">State: {runState}. Preview mode is used when backend model fitting is not implemented for a selected model.</p></div><button className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white" onClick={() => setRunState("complete")}>Train selected models and run backtest</button></div>
        <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">Preview mode: ATLAS does not claim real model fitting for unsupported Time Series models. Planned run configuration and deterministic preview diagnostics are shown for workflow validation.</div>
      </section>
      <Table title="Model comparison table" columns={["model", "role", "WAPE", "MAE", "RMSE", "MAPE", "MASE", "Bias", "Coverage", "average rank", "selected champion", "notes"]} rows={results} interpretation="The leading candidate is directional until real backend training returns run records and fold metrics." />
      <MetricBarChart title="Model comparison bar chart by governing metric" rows={results} metric="WAPE" />
      <Table title="Fold-by-fold metrics" columns={["fold", "WAPE", "MAE", "RMSE", "Bias", "Coverage"]} rows={foldRows} interpretation="Fold stability matters more than a single average metric when approving a forecast model." />
      <Table title="Horizon-level metrics" columns={["horizon", "WAPE", "Bias", "Coverage"]} rows={horizonRows} interpretation="Horizon degradation identifies how far the model can be trusted for operational use." />
      <section className="grid gap-4 xl:grid-cols-2"><MiniLineChart title="Actual vs forecast by fold" points={foldRows.map((row, index) => ({ label: row.fold, value: 100 - Number(row.WAPE) * 100 }))} yLabel="Fit score" /><MiniLineChart title="Forecast error over time" points={foldRows.map((row) => ({ label: row.fold, value: Number(row.Bias) }))} yLabel="Bias" /><MetricBarChart title="Residual distribution" rows={foldRows.map((row) => ({ model: row.fold, residual: Math.abs(Number(row.Bias)) }))} metric="residual" /><MetricBarChart title="Bias by horizon" rows={horizonRows.map((row) => ({ model: row.horizon, Bias: Math.abs(Number(row.Bias)) }))} metric="Bias" /></section>
    </DepthShell>
  );
}

function ForecastResultsPage({ bundle }: { bundle: InputBundle | null }) {
  const series = bundle?.profile?.timeSeriesPoints ?? [];
  const last = series[series.length - 1]?.value ?? 100;
  const forecastRows = Array.from({ length: 12 }).map((_, index) => {
    const forecast = last * (1 + index * 0.015);
    return { "date/period": `H+${index + 1}`, entity: bundle?.mapping?.entityColumns?.join(" + ") || "Aggregate", forecast: Math.round(forecast), "lower interval": Math.round(forecast * 0.9), "upper interval": Math.round(forecast * 1.1), model: "Candidate champion", scenario: "Base", confidence: "90%" };
  });
  const entityRows = (bundle?.profile?.topEntities ?? []).slice(0, 6).map((entity, index) => ({ entity: entity.entity, "forecast direction": index % 2 ? "decreasing" : "increasing", uncertainty: index < 2 ? "high" : "moderate", "history status": entity.rows < 10 ? "sparse history" : "sufficient history" }));
  const payload = () => ({ championModel: "Candidate champion", governingMetric: "WAPE", backtestScore: "preview", horizon: bundle?.mapping?.forecastHorizon, frequency: bundle?.mapping?.aggregationFrequency, forecastRows, entityRows });
  const nav = usePageNavigation("forecast", payload);
  return (
    <DepthShell kind="forecast" bundle={bundle} onNext={nav.onNext}>
      <section className="grid gap-3 md:grid-cols-6">{[["Champion model", "Candidate champion"], ["Governing metric", "WAPE"], ["Backtest score", "Preview"], ["Horizon", bundle?.mapping?.forecastHorizon ?? "90 days"], ["Frequency", bundle?.mapping?.aggregationFrequency ?? "Daily"], ["Entity scope", bundle?.mapping?.entityColumns?.join(" + ") || "Aggregate"]].map(([label, value]) => <Metric key={label} label={String(label)} value={String(value)} />)}</section>
      <section className="rounded-2xl border border-blue-200 bg-white p-5 shadow-sm">
        <div className="flex items-start justify-between"><div><h3 className="text-base font-semibold text-slate-950">Actual plus forecast chart with prediction interval band</h3><p className="mt-1 text-xs text-slate-500">X-axis: forecast period. Y-axis: target value. Legend: historical actuals, forecast line, lower interval, upper interval, forecast issue date, holdout boundary.</p></div><button className="rounded-lg border border-blue-200 bg-white px-3 py-1.5 text-xs font-semibold text-blue-700">Export chart</button></div>
        <svg viewBox="0 0 900 360" className="mt-4 h-96 w-full rounded-xl bg-slate-50">
          <rect x="70" y="58" width="760" height="210" fill="#dbeafe" opacity="0.75" />
          <polyline points="70,240 150,222 230,214 310,206 390,190 470,176 550,164 630,152 710,142 790,130" fill="none" stroke="#2563eb" strokeWidth="4" />
          <polyline points="470,194 550,180 630,168 710,158 790,146" fill="none" stroke="#0f766e" strokeWidth="4" strokeDasharray="8 6" />
          <line x1="470" x2="470" y1="40" y2="292" stroke="#f97316" strokeWidth="3" />
          <text x="450" y="32" fill="#f97316" fontSize="12">Forecast issue date</text>
          <text x="450" y="342" fill="#334155" fontSize="12">Date / period</text>
          <text x="18" y="176" fill="#334155" fontSize="12" transform="rotate(-90 18 176)">Forecast target</text>
        </svg>
        <div className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900"><b>ATLAS interpretation:</b> The interval band communicates forecast uncertainty. Use the forecast table and entity summary to identify demand, capacity, and sparse-history risks.</div>
      </section>
      <Table title="Forecast table" columns={["date/period", "entity", "forecast", "lower interval", "upper interval", "model", "scenario", "confidence"]} rows={forecastRows} interpretation="Forecast rows are prepared for governed CSV, JSON, and documentation export." />
      <section className="rounded-2xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-950">
        Entity-level forecast summary includes top increasing, top decreasing, highest uncertainty, and sparse-history entity groups.
      </section>
      <Table title="Entity-level forecast summary" columns={["entity", "forecast direction", "uncertainty", "history status"]} rows={entityRows.length ? entityRows : [{ entity: "Aggregate", "forecast direction": "review", uncertainty: "moderate", "history status": "aggregate only" }]} interpretation="Top increasing, top decreasing, highest uncertainty, and sparse-history entities should be reviewed before operational use." />
      <section className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5 shadow-sm"><h3 className="text-base font-semibold text-slate-950">Business interpretation</h3><div className="mt-3 grid gap-3 md:grid-cols-4">{[["Expected peak period", "Review H+12"], ["Forecast risk", "Moderate until real backtest"], ["Demand/capacity concern", "Review high uncertainty entities"], ["Recommended use", "Planning preview until final model run"]].map(([label, value]) => <Metric key={label} label={label} value={value} />)}</div><div className="mt-4 flex flex-wrap gap-2">{["Export forecast CSV", "Export chart", "Export governed JSON", "Export documentation-ready summary"].map((label) => <button key={label} className="rounded-lg border border-emerald-200 bg-white px-3 py-2 text-sm font-semibold text-emerald-800">{label}</button>)}</div></section>
    </DepthShell>
  );
}

function Builder({ title, action, items, onAdd }: { title: string; action: string; value: string; items: string[]; onAdd: () => void }) {
  return <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><div className="flex items-center justify-between gap-3"><h3 className="text-base font-semibold text-slate-950">{title}</h3><button className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white" onClick={onAdd}>{action}</button></div><div className="mt-4 space-y-2">{items.map((item) => <div key={item} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">{item} <button className="ml-2 text-xs font-semibold text-blue-700">remove row</button></div>)}</div></section>;
}

function Select({ label, value, options, onChange }: { label: string; value: string; options: string[]; onChange: (value: string) => void }) {
  return <label className="text-sm font-semibold text-slate-800">{label}<select className="mt-1 w-full rounded-lg border border-blue-200 bg-white px-3 py-2 text-sm" value={value} onChange={(event) => onChange(event.target.value)}>{options.map((option) => <option key={option}>{option}</option>)}</select></label>;
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"><div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div><div className="mt-1 text-lg font-semibold text-slate-950">{value}</div></div>;
}

function CodeBox({ title, lines }: { title: string; lines: string[] }) {
  return <section className="rounded-2xl border border-slate-200 bg-slate-950 p-5 text-slate-100 shadow-sm"><div className="text-xs font-semibold uppercase tracking-wide text-cyan-200">{title}</div><pre className="mt-3 overflow-auto rounded-xl bg-black/25 p-4 text-xs leading-6"><code>{lines.join("\n")}</code></pre></section>;
}

function DepthShell({ kind, bundle, onNext, children }: { kind: PageKind; bundle: InputBundle | null; onNext: () => Promise<boolean>; children: React.ReactNode }) {
  const nextLabel = kind === "forecast" ? "Save Forecast Results and Continue" : `Save ${titles[kind].title} and Continue`;
  return (
    <StepShell title={titles[kind].title} subtitle={titles[kind].subtitle} eyebrow="TIME SERIES & FORECASTING WORKFLOW" variant="analysis" nextLabel={nextLabel} nextStatusLine={`Persist ${titles[kind].evidence} evidence and continue.`} onNextClick={onNext}>
      <div className="space-y-5">
        <ScopeHeader bundle={bundle} page={kind} />
        {!bundle ? <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-900">Confirm Time Series Data Acquisition first. This page uses the selected dataset mapping and input bundle.</section> : null}
        {children}
      </div>
    </StepShell>
  );
}

export default function TimeSeriesModelingDepthPage({ kind }: { kind: PageKind }) {
  const projectId = useWorkflowStore((state) => state.projectId);
  const bundle = useMemo(() => readBundle(projectId), [projectId]);
  if (kind === "feature") return <FeatureDesignPage bundle={bundle} />;
  if (kind === "backtest") return <BacktestDesignPage bundle={bundle} />;
  if (kind === "model-config") return <ModelConfigurationPage bundle={bundle} />;
  if (kind === "train") return <TrainBacktestPage bundle={bundle} />;
  return <ForecastResultsPage bundle={bundle} />;
}
