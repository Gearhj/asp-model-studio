// src/steps/Step02_EDA.tsx
import React, { useEffect, useMemo, useState } from "react";
import ErrorBoundary from "../components/ErrorBoundary";
import D3HistogramStackedGrouped from "../components/D3HistogramStackedGrouped";
import D3Boxplot from "../components/D3Boxplot";
import D3Heatmap from "../components/D3Heatmap";
import D3Pairplot from "../components/D3Pairplot";
import { PairwiseSvg } from "../components/D3Pairplot";
import StepPythonPanel from "../components/StepPythonPanel";
import { useNavigate } from "react-router-dom";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { inferLocalColumns, inferLocalProblemType, loadLocalDataset, type LocalDataset } from "../lib/localDataset";
import { upsertProjectFromState } from "../lib/localProjects";

type ColumnInfo = { name: string; dtype?: string; role?: "feature" | "target" };

const BASE =
  (import.meta as any)?.env?.VITE_API_BASE?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

const edaCorrelationCache = new Map<string, { columns: string[]; values: number[][] }>();

export default function Step02_EDA() {
  const navigate = useNavigate();
  const markComplete = useWorkflowStore((state) => state.markComplete);

  // controls
  const [columns, setColumns] = useState<ColumnInfo[]>([]);
  const [target, setTarget] = useState<string>("");
  const [feature, setFeature] = useState<string>("");
  const [bins, setBins] = useState<number>(20);
  const [layout, setLayout] = useState<"grouped" | "stacked">("grouped");
  const [samplePct, setSamplePct] = useState<number>(10);

  // status
  const [loading, setLoading] = useState<boolean>(true);
  const [errMsg, setErrMsg] = useState<string>("");
  const [navigationError, setNavigationError] = useState<string>("");
  const [usingLocalDataset, setUsingLocalDataset] = useState(false);
  const [localDataset, setLocalDataset] = useState<LocalDataset | null>(null);
  const [analysisDataset, setAnalysisDataset] = useState<LocalDataset | null>(null);

  // Ask backend what columns/target are currently loaded.
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        setLoading(true);
        setErrMsg("");
        let cols: ColumnInfo[] = [];
        let backendTarget = "";

        try {
          const r = await fetch(`${BASE}/columns`);
          if (!r.ok) throw new Error(`GET /columns -> ${r.status}`);
          const js = await r.json();
          cols = Array.isArray(js?.columns) ? js.columns : [];
          backendTarget = typeof js?.target === "string" ? js.target : "";
        } catch (backendError) {
          console.warn("[EDA] Backend columns unavailable; checking local dataset cache.", backendError);
        }

        const cachedDataset = loadLocalDataset();
        if (cachedDataset?.headers.length) {
          setUsingLocalDataset(true);
          setLocalDataset(cachedDataset);
          setAnalysisDataset(cachedDataset);
          const allowedHeaders = new Set(cachedDataset.headers);
          if (cols.length) {
            cols = cols.filter((column) => allowedHeaders.has(column.name));
            backendTarget = cachedDataset.target ?? backendTarget;
          } else {
            cols = inferLocalColumns(cachedDataset);
            backendTarget = cachedDataset.target ?? "";
          }
        } else {
          setUsingLocalDataset(false);
          setLocalDataset(null);
          setAnalysisDataset(null);
        }

        if (!alive) return;
        setColumns(cols);

        if (cols.length === 0) {
          setErrMsg(
            "No dataset has been uploaded/selected. Please go back to Step 1 (Data Acquisition) and load a CSV."
          );
          return;
        }

        // find target
        const tgt =
          backendTarget ||
          cols.find((c) => c.role === "target")?.name ||
          cols.find((c) => /^fraud|target|label$/i.test(c.name))?.name ||
          "";
        setTarget(tgt);

        if (!cachedDataset?.headers.length && tgt) {
          try {
            const sampleResponse = await fetch(`${BASE}/data/get_sample?max_rows=5000`);
            if (sampleResponse.ok) {
              const sample = await sampleResponse.json();
              const headers = Array.isArray(sample?.headers) ? sample.headers.map(String) : [];
              const rows = Array.isArray(sample?.rows) ? sample.rows : [];
              const sampleTarget = typeof sample?.target === "string" ? sample.target : tgt;
              if (headers.length && rows.length && sampleTarget && headers.includes(sampleTarget)) {
                setAnalysisDataset({
                  headers,
                  rows,
                  target: sampleTarget,
                  selected_columns: headers.filter((header: string) => header !== sampleTarget),
                });
              }
            }
          } catch (sampleError) {
            console.warn("[EDA] Backend sample unavailable for target analysis.", sampleError);
          }
        }

        // pick default feature (first non-target)
        const firstFeat = cols.find((c) => c.name !== tgt)?.name ?? "";
        setFeature(firstFeat);
      } catch (e: any) {
        setErrMsg(e?.message || "Failed to load columns.");
      } finally {
        if (alive) setLoading(false);
      }
    })();

    return () => {
      alive = false;
    };
  }, []);

  const featureOptions = useMemo(
    () => columns.filter((c) => c.name !== target).map((c) => c.name),
    [columns, target]
  );

  async function handleContinue() {
    try {
      setNavigationError("");
      markComplete("step02");
      await upsertProjectFromState(useWorkflowStore.getState());
      navigate("/step03");
      window.scrollTo({ top: 0, left: 0 });
    } catch (error: any) {
      setNavigationError(error?.message ?? "ATLAS could not save this step before navigating.");
    }
  }

  // Hard guards so the page never shows a blank screen
  if (loading) {
    return (
      <div className="p-6">
        <h2 className="text-xl font-semibold mb-2">Step 2 — Exploratory Data Analysis</h2>
        <p className="text-gray-500">Loading…</p>
      </div>
    );
  }

  if (errMsg) {
    return (
      <div className="p-6">
        <h2 className="text-xl font-semibold mb-2">Step 2 — Exploratory Data Analysis</h2>
        <div className="rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800">
          {errMsg}
        </div>
        <div className="mt-3">
          <button
            className="px-3 py-2 rounded bg-indigo-600 text-white hover:bg-indigo-700"
            onClick={() => navigate("/step01")}
          >
            Go to Data Acquisition
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6">
      <h2 className="text-xl font-semibold mb-4">Step 2 — Exploratory Data Analysis</h2>

      {/* Controls */}
      <div className="mb-4 flex flex-wrap gap-4 items-end">
        <label className="flex items-center gap-2">
          <span className="text-sm text-gray-600">Feature</span>
          <select
            className="border rounded px-2 py-1"
            value={feature}
            onChange={(e) => setFeature(e.target.value)}
          >
            {featureOptions.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        </label>

        <label className="flex items-center gap-2">
          <span className="text-sm text-gray-600">Render Sample %</span>
          <select
            className="border rounded px-2 py-1"
            value={samplePct}
            onChange={(e) => setSamplePct(Number(e.target.value))}
          >
            {[5, 10, 20, 50, 100].map((p) => (
              <option key={p} value={p}>
                {p}%
              </option>
            ))}
          </select>
        </label>

        <label className="flex items-center gap-2">
          <span className="text-sm text-gray-600">Bins</span>
          <input
            type="range"
            min={5}
            max={60}
            step={1}
            value={bins}
            onChange={(e) => setBins(Number(e.target.value))}
          />
          <span className="text-sm text-gray-700 w-10 text-center">{bins}</span>
        </label>

        <label className="flex items-center gap-2">
          <span className="text-sm text-gray-600">Layout</span>
          <select
            className="border rounded px-2 py-1"
            value={layout}
            onChange={(e) => setLayout(e.target.value as "grouped" | "stacked")}
          >
            <option value="grouped">Grouped</option>
            <option value="stacked">Stacked</option>
          </select>
        </label>
      </div>

      {analysisDataset && target && (
        <TargetVariableAnalysis dataset={analysisDataset} target={target} problemType={inferLocalProblemType(analysisDataset) ?? analysisDataset.problem_type ?? "classification"} />
      )}

      {/* Row 1: Histogram + Boxplot */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <div className="rounded border bg-white p-4">
          <div className="text-sm font-medium mb-2">Histogram</div>
          {usingLocalDataset && localDataset ? (
            <LocalHistogram dataset={localDataset} feature={feature} bins={bins} samplePct={samplePct} />
          ) : (
            <ErrorBoundary title="Histogram failed to render">
              <D3HistogramStackedGrouped
                feature={feature}
                bins={bins}
                layout={layout}
                samplePct={samplePct}
              />
            </ErrorBoundary>
          )}
        </div>

        <div className="rounded border bg-white p-4">
          <div className="text-sm font-medium mb-2">Box-Plot</div>
          {usingLocalDataset && localDataset ? (
            <LocalBoxplot dataset={localDataset} feature={feature} samplePct={samplePct} />
          ) : (
            <ErrorBoundary title="Box-plot failed to render">
              <D3Boxplot feature={feature} samplePct={samplePct} />
            </ErrorBoundary>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mt-6">
        <div className="rounded border bg-white p-4">
          <div className="text-sm font-medium mb-2">Dataset Profile</div>
          <DatasetProfile columns={columns} target={target} dataset={localDataset} />
        </div>
        <div className="rounded border bg-white p-4 lg:col-span-2">
          <div className="text-sm font-medium mb-2">Missingness Snapshot</div>
          <MissingnessSnapshot dataset={localDataset} columns={columns} />
        </div>
      </div>

      {/* Relationship analysis */}
      <div className="grid grid-cols-1 gap-6 mt-6 2xl:grid-cols-2">
        <div className="rounded border bg-white p-4">
          <div className="text-sm font-medium mb-2">Correlation Heatmap</div>
          {usingLocalDataset && localDataset ? (
            <LocalCorrelation dataset={localDataset} samplePct={samplePct} />
          ) : (
            <ErrorBoundary title="Heatmap failed to render">
              <D3Heatmap samplePct={samplePct} limit={20} />
            </ErrorBoundary>
          )}
        </div>

        <div className="rounded border bg-white p-4">
          <div className="text-sm font-medium mb-2">Pairwise Plots</div>
          {usingLocalDataset && localDataset ? (
            <LocalPairwisePlot dataset={localDataset} samplePct={samplePct} />
          ) : (
            <ErrorBoundary title="Pairwise plots failed to render">
              <D3Pairplot samplePct={samplePct} />
            </ErrorBoundary>
          )}
        </div>
      </div>

      <StepPythonPanel />

      {/* Bottom nav */}
      <div className="mt-8 flex flex-col items-center gap-3">
        {navigationError && (
          <div className="w-full max-w-2xl rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
            {navigationError}
          </div>
        )}
        <button
          className="px-4 py-2 rounded bg-indigo-600 text-white hover:bg-indigo-700"
          onClick={handleContinue}
        >
          Mark Complete & Next Step
        </button>
      </div>
    </div>
  );
}

function mean(values: number[]) {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
}

function std(values: number[]) {
  if (values.length < 2) return 0;
  const m = mean(values);
  return Math.sqrt(values.reduce((sum, value) => sum + (value - m) ** 2, 0) / (values.length - 1));
}

function skewness(values: number[]) {
  const s = std(values);
  if (!values.length || !s) return 0;
  const m = mean(values);
  return values.reduce((sum, value) => sum + ((value - m) / s) ** 3, 0) / values.length;
}

function kurtosis(values: number[]) {
  const s = std(values);
  if (!values.length || !s) return 0;
  const m = mean(values);
  return values.reduce((sum, value) => sum + ((value - m) / s) ** 4, 0) / values.length - 3;
}

function corr(rows: Record<string, any>[], xName: string, yName: string) {
  const pairs = rows
    .map((row) => ({ x: Number(row[xName]), y: Number(row[yName]) }))
    .filter((row) => Number.isFinite(row.x) && Number.isFinite(row.y));
  if (pairs.length < 3) return 0;
  const mx = pairs.reduce((sum, row) => sum + row.x, 0) / pairs.length;
  const my = pairs.reduce((sum, row) => sum + row.y, 0) / pairs.length;
  const numerator = pairs.reduce((sum, row) => sum + (row.x - mx) * (row.y - my), 0);
  const dx = Math.sqrt(pairs.reduce((sum, row) => sum + (row.x - mx) ** 2, 0));
  const dy = Math.sqrt(pairs.reduce((sum, row) => sum + (row.y - my) ** 2, 0));
  const value = numerator / ((dx || 0) * (dy || 0));
  return Number.isFinite(value) ? value : 0;
}

function TargetVariableAnalysis({
  dataset,
  target,
  problemType,
}: {
  dataset: LocalDataset;
  target: string;
  problemType: string;
}) {
  const values = dataset.rows.map((row) => Number(row[target])).filter(Number.isFinite);
  const sorted = [...values].sort((a, b) => a - b);
  const missing = dataset.rows.length - values.length;
  const numericFeatureNames = dataset.headers
    .filter((header) => header !== target)
    .filter((header) => dataset.rows.slice(0, 250).some((row) => Number.isFinite(Number(row[header]))));
  const topCorrelations = numericFeatureNames
    .map((feature) => ({ feature, value: corr(dataset.rows, feature, target) }))
    .filter((row) => Number.isFinite(row.value))
    .sort((a, b) => Math.abs(b.value) - Math.abs(a.value))
    .slice(0, 8);
  const hasGeo = dataset.headers.includes("Latitude") && dataset.headers.includes("Longitude");
  const stats = [
    ["Rows", dataset.rows.length.toLocaleString()],
    ["Missing %", dataset.rows.length ? `${((missing / dataset.rows.length) * 100).toFixed(2)}%` : "-"],
    ["Mean", values.length ? mean(values).toFixed(4) : "-"],
    ["Median", values.length ? quantile(sorted, 0.5).toFixed(4) : "-"],
    ["Std Dev", values.length ? std(values).toFixed(4) : "-"],
    ["Min", values.length ? Math.min(...values).toFixed(4) : "-"],
    ["Max", values.length ? Math.max(...values).toFixed(4) : "-"],
    ["Skewness", values.length ? skewness(values).toFixed(3) : "-"],
    ["Kurtosis", values.length ? kurtosis(values).toFixed(3) : "-"],
  ];
  const percentiles = [
    ["P1", 0.01],
    ["P5", 0.05],
    ["P25", 0.25],
    ["P50", 0.5],
    ["P75", 0.75],
    ["P95", 0.95],
    ["P99", 0.99],
  ];
  const skew = values.length ? skewness(values) : 0;
  const kurt = values.length ? kurtosis(values) : 0;
  const tailReadout =
    Math.abs(skew) > 1
      ? `${skew > 0 ? "Right" : "Left"}-skewed target distribution; review tail behavior before choosing split and residual diagnostics.`
      : "Target distribution is not strongly skewed; residual diagnostics should still confirm tail behavior.";
  const kurtosisReadout =
    kurt > 1
      ? "Kurtosis suggests heavier tails than a normal distribution."
      : kurt < -1
        ? "Kurtosis suggests a flatter distribution with lighter tails."
        : "Kurtosis is broadly near normal-range tail behavior.";
  return (
    <section className="mb-6 rounded-2xl border border-blue-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Target Variable Analysis</div>
          <h3 className="mt-1 text-lg font-semibold text-slate-950">{target}</h3>
          <p className="mt-1 text-sm text-slate-600">
            {problemType === "regression"
              ? "Continuous target diagnostics drive the rest of the regression workflow: split alignment, residual analysis, and scoring drift."
              : "Target diagnostics drive event-rate checks, class balance, and rare-event recommendations."}
          </p>
        </div>
        <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-semibold text-slate-700">
          {problemType}
        </span>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-3 xl:grid-cols-5">
        {stats.map(([label, value]) => (
          <div key={label} className="rounded-xl border border-slate-100 bg-slate-50 p-3">
            <div className="text-[11px] font-semibold uppercase text-slate-500">{label}</div>
            <div className="mt-1 text-base font-semibold text-slate-950">{value}</div>
          </div>
        ))}
      </div>
      <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(320px,0.8fr)]">
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
          <div className="mb-2 text-sm font-semibold text-slate-800">Target Distribution</div>
          <TargetHistogram values={values} meanValue={mean(values)} medianValue={quantile(sorted, 0.5)} quartiles={[quantile(sorted, 0.25), quantile(sorted, 0.75)]} />
          <ChartReadout
            what="Shows the target value distribution with mean, median, and quartile reference markers."
            good="Good looks like a distribution that is understood and stable enough for split and residual diagnostics."
            sees={`${tailReadout} ${kurtosisReadout}`}
          />
        </div>
        <div className="grid gap-4">
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="mb-2 text-sm font-semibold text-slate-800">Percentiles</div>
            <div className="grid grid-cols-2 gap-2 text-sm">
              {percentiles.map(([label, p]) => (
                <div key={String(label)} className="flex justify-between rounded-lg bg-slate-50 px-3 py-2">
                  <span className="font-medium text-slate-600">{String(label)}</span>
                  <span className="font-semibold text-slate-900">{values.length ? quantile(sorted, Number(p)).toFixed(4) : "-"}</span>
                </div>
              ))}
            </div>
          </div>
          {hasGeo && (
            <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900">
              <div className="font-semibold">Geo target analysis available</div>
              <p className="mt-1">
                Latitude and Longitude were detected. ATLAS recommends a geographic target scatterplot to identify spatial price/error patterns.
              </p>
            </div>
          )}
        </div>
      </div>
      <div className="mt-5 rounded-xl border border-slate-200 bg-white p-4">
        <div className="mb-3 text-sm font-semibold text-slate-800">Top Features by Corr(Target)</div>
        <p className="mb-3 text-xs leading-5 text-slate-500">
          Ranked signed correlations. Green bars move with the target; rose bars move opposite the target.
        </p>
        <div className="space-y-2">
          {topCorrelations.map((row) => {
            const strength = Math.abs(row.value) >= 0.5 ? "strong" : Math.abs(row.value) >= 0.25 ? "moderate" : "weak";
            const width = `${Math.max(4, Math.min(100, Math.abs(row.value) * 100))}%`;
            return (
              <div key={row.feature} className="grid grid-cols-[160px_minmax(0,1fr)_82px_78px] items-center gap-3 text-sm">
                <div className="truncate font-medium text-slate-700" title={row.feature}>{row.feature}</div>
                <div className="h-2 overflow-hidden rounded-full bg-slate-100">
                  <div className={`h-full rounded-full ${row.value >= 0 ? "bg-emerald-500" : "bg-rose-500"}`} style={{ width }} />
                </div>
                <div className="text-right font-semibold text-slate-800">{row.value.toFixed(3)}</div>
                <div className={`rounded-full px-2 py-1 text-center text-[11px] font-semibold ${strength === "strong" ? "bg-emerald-50 text-emerald-700" : strength === "moderate" ? "bg-blue-50 text-blue-700" : "bg-slate-50 text-slate-600"}`}>
                  {strength}
                </div>
              </div>
            );
          })}
          {!topCorrelations.length && <div className="text-sm text-slate-500">No numeric feature correlations were available.</div>}
        </div>
      </div>
    </section>
  );
}

function ChartReadout({ what, good, sees }: { what: string; good: string; sees: string }) {
  const clean = (value: string) => value.replace(/^(shows|good looks like|good|atlas found|atlas):\s*/i, "");
  return (
    <div className="mt-3 grid gap-2 rounded-lg border border-slate-200 bg-white p-3 text-xs leading-5 text-slate-600 md:grid-cols-3">
      <div><span className="font-semibold text-slate-800">Shows: </span>{clean(what)}</div>
      <div><span className="font-semibold text-slate-800">Good: </span>{clean(good)}</div>
      <div><span className="font-semibold text-slate-800">ATLAS: </span>{clean(sees)}</div>
    </div>
  );
}

function niceTicks(min: number, max: number, count = 5) {
  if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) return [min || 0];
  return Array.from({ length: count }, (_, index) => min + ((max - min) * index) / (count - 1));
}

function TargetHistogram({ values, meanValue, medianValue, quartiles }: { values: number[]; meanValue: number; medianValue: number; quartiles: [number, number] }) {
  const width = 760;
  const height = 300;
  const pad = 50;
  if (!values.length) return <div className="flex h-[240px] items-center justify-center text-sm text-slate-500">No numeric target values available.</div>;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const bins = 32;
  const counts = new Array(bins).fill(0);
  values.forEach((value) => {
    const index = Math.max(0, Math.min(bins - 1, Math.floor(((value - min) / (max - min || 1)) * bins)));
    counts[index] += 1;
  });
  const maxCount = Math.max(...counts, 1);
  const plotWidth = width - pad * 1.4;
  const plotHeight = height - pad * 1.5;
  const x = (value: number) => pad + ((value - min) / (max - min || 1)) * plotWidth;
  const y = (count: number) => height - pad - (count / maxCount) * plotHeight;
  const barWidth = plotWidth / bins;
  const xTicks = niceTicks(min, max, 6);
  const yTicks = niceTicks(0, maxCount, 5);
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-[300px] w-full rounded-xl bg-white">
      {yTicks.map((tick) => (
        <g key={`y-${tick}`}>
          <line x1={pad} y1={y(tick)} x2={width - pad / 2} y2={y(tick)} stroke="#e2e8f0" />
          <text x={pad - 8} y={y(tick) + 4} textAnchor="end" className="fill-slate-500 text-[10px]">{Math.round(tick).toLocaleString()}</text>
        </g>
      ))}
      <line x1={pad} y1={height - pad} x2={width - pad / 2} y2={height - pad} stroke="#cbd5e1" />
      <line x1={pad} y1={pad / 2} x2={pad} y2={height - pad} stroke="#cbd5e1" />
      {counts.map((count, index) => {
        const barX = pad + index * barWidth;
        const barY = y(count);
        return <rect key={index} x={barX + 1} y={barY} width={Math.max(2, barWidth - 2)} height={height - pad - barY} rx={3} fill="#2563eb" opacity={0.72} />;
      })}
      {quartiles.map((quartile, index) => (
        <line key={`q-${index}`} x1={x(quartile)} x2={x(quartile)} y1={pad / 2} y2={height - pad} stroke="#94a3b8" strokeWidth={1.5} strokeDasharray="2 5" />
      ))}
      <line x1={x(meanValue)} x2={x(meanValue)} y1={pad / 2} y2={height - pad} stroke="#dc2626" strokeWidth={2} strokeDasharray="5 4" />
      <line x1={x(medianValue)} x2={x(medianValue)} y1={pad / 2} y2={height - pad} stroke="#059669" strokeWidth={2} strokeDasharray="5 4" />
      {xTicks.map((tick) => (
        <g key={`x-${tick}`}>
          <line x1={x(tick)} x2={x(tick)} y1={height - pad} y2={height - pad + 5} stroke="#94a3b8" />
          <text x={x(tick)} y={height - pad + 18} textAnchor="middle" className="fill-slate-500 text-[10px]">{tick.toFixed(2)}</text>
        </g>
      ))}
      <text x={x(meanValue) + 4} y={26} className="fill-rose-700 text-[11px]">Mean</text>
      <text x={x(medianValue) + 4} y={42} className="fill-emerald-700 text-[11px]">Median</text>
      <text x={x(quartiles[0]) + 4} y={58} className="fill-slate-500 text-[10px]">Q1</text>
      <text x={x(quartiles[1]) + 4} y={72} className="fill-slate-500 text-[10px]">Q3</text>
      <text x={width / 2} y={height - 8} textAnchor="middle" className="fill-slate-600 text-[11px]">Target value</text>
      <text x={14} y={height / 2} textAnchor="middle" transform={`rotate(-90 14 ${height / 2})`} className="fill-slate-600 text-[11px]">Records</text>
    </svg>
  );
}

function sampledRows(dataset: LocalDataset, samplePct: number) {
  const pct = Math.max(1, Math.min(100, samplePct || 10));
  const count = Math.max(1, Math.ceil(dataset.rows.length * (pct / 100)));
  return dataset.rows.slice(0, count);
}

function numericValues(dataset: LocalDataset, feature: string, samplePct = 100) {
  return sampledRows(dataset, samplePct)
    .map((row) => Number(row[feature]))
    .filter((value) => Number.isFinite(value));
}

function quantile(sorted: number[], p: number) {
  if (!sorted.length) return 0;
  const index = (sorted.length - 1) * p;
  const lower = Math.floor(index);
  const upper = Math.ceil(index);
  const weight = index - lower;
  return sorted[lower] * (1 - weight) + sorted[upper] * weight;
}

function datasetCacheKey(dataset: LocalDataset, samplePct: number) {
  return [
    dataset.headers.join(","),
    dataset.target ?? "",
    dataset.rows.length,
    samplePct,
    JSON.stringify(dataset.rows.slice(0, 3)),
  ].join("|");
}

function cachedCorrelationMatrix(dataset: LocalDataset, samplePct: number) {
  const key = datasetCacheKey(dataset, samplePct);
  const cached = edaCorrelationCache.get(key);
  if (cached) return cached;

  const numericColumns = dataset.headers.filter((header) => numericValues(dataset, header, samplePct).length >= 3).slice(0, 20);
  const values = numericColumns.map((rowColumn) => numericColumns.map((column) => pearson(dataset, rowColumn, column, samplePct)));
  const result = { columns: numericColumns, values };
  edaCorrelationCache.set(key, result);
  if (edaCorrelationCache.size > 12) {
    const oldest = edaCorrelationCache.keys().next().value;
    if (oldest) edaCorrelationCache.delete(oldest);
  }
  return result;
}

function LocalHistogram({ dataset, feature, bins, samplePct }: { dataset: LocalDataset; feature: string; bins: number; samplePct: number }) {
  const values = numericValues(dataset, feature, samplePct);
  if (!values.length) {
    return <div className="text-sm text-gray-500">Select a numeric feature to render a local histogram.</div>;
  }

  const min = Math.min(...values);
  const max = Math.max(...values);
  const width = max - min || 1;
  const bucketCount = Math.min(60, Math.max(5, bins));
  const counts = Array.from({ length: bucketCount }, () => 0);
  values.forEach((value) => {
    const index = Math.min(bucketCount - 1, Math.floor(((value - min) / width) * bucketCount));
    counts[index] += 1;
  });

  const maxCount = Math.max(...counts, 1);
  const chartWidth = 820;
  const chartHeight = 270;
  const pad = 46;
  const plotWidth = chartWidth - pad * 1.4;
  const plotHeight = chartHeight - pad * 1.45;
  const barWidth = plotWidth / bucketCount;
  const sorted = [...values].sort((a, b) => a - b);
  const meanValue = mean(values);
  const medianValue = quantile(sorted, 0.5);
  const x = (value: number) => pad + ((value - min) / (max - min || 1)) * plotWidth;
  const y = (count: number) => chartHeight - pad - (count / maxCount) * plotHeight;
  const xTicks = niceTicks(min, max, 5);
  const yTicks = niceTicks(0, maxCount, 4);

  return (
    <div>
      <svg viewBox={`0 0 ${chartWidth} ${chartHeight}`} className="h-[280px] w-full rounded-xl bg-white">
      {yTicks.map((tick) => (
        <g key={`y-${tick}`}>
          <line x1={pad} x2={pad + plotWidth} y1={y(tick)} y2={y(tick)} stroke="#e2e8f0" />
          <text x={pad - 8} y={y(tick) + 4} textAnchor="end" fontSize="10" fill="#64748b">{Math.round(tick)}</text>
        </g>
      ))}
      <line x1={pad} y1={chartHeight - pad} x2={pad + plotWidth} y2={chartHeight - pad} stroke="#94a3b8" />
      <line x1={pad} y1={chartHeight - pad} x2={pad} y2={chartHeight - pad - plotHeight} stroke="#cbd5e1" />
      {counts.map((count, index) => {
        const height = ((plotHeight) * count) / maxCount;
        return (
          <rect
            key={index}
            x={pad + index * barWidth + 1}
            y={chartHeight - pad - height}
            width={Math.max(1, barWidth - 2)}
            height={height}
            rx={2}
            fill="#2563eb"
            opacity={0.82}
          />
        );
      })}
      {[{ label: "Mean", value: meanValue, color: "#0f766e" }, { label: "Median", value: medianValue, color: "#f97316" }].map((marker) => (
        <g key={marker.label}>
          <line x1={x(marker.value)} x2={x(marker.value)} y1={chartHeight - pad - plotHeight} y2={chartHeight - pad} stroke={marker.color} strokeWidth={2} strokeDasharray="4 4" />
          <text x={x(marker.value) + 5} y={chartHeight - pad - plotHeight + 14} fontSize="10" fill={marker.color}>{marker.label}</text>
        </g>
      ))}
      {xTicks.map((tick) => (
        <g key={`x-${tick}`}>
          <line x1={x(tick)} x2={x(tick)} y1={chartHeight - pad} y2={chartHeight - pad + 5} stroke="#94a3b8" />
          <text x={x(tick)} y={chartHeight - 12} textAnchor="middle" fontSize="10" fill="#64748b">{tick.toFixed(2)}</text>
        </g>
      ))}
      <text x={pad + plotWidth / 2} y={chartHeight - 2} textAnchor="middle" fontSize="11" fill="#475569">{feature}</text>
    </svg>
    <ChartReadout
      what={`${feature} distribution with count axis, value ticks, mean, and median markers.`}
      good="A stable feature has a readable range, limited extreme tails, and no suspicious spikes caused by coding artifacts."
      sees={`Sampled ${values.length.toLocaleString()} records; mean ${meanValue.toFixed(3)}, median ${medianValue.toFixed(3)}.`}
    />
    </div>
  );
}

function LocalBoxplot({ dataset, feature, samplePct }: { dataset: LocalDataset; feature: string; samplePct: number }) {
  const values = numericValues(dataset, feature, samplePct).sort((a, b) => a - b);
  if (!values.length) {
    return <div className="text-sm text-gray-500">Select a numeric feature to render a local box plot.</div>;
  }

  const min = values[0];
  const q1 = quantile(values, 0.25);
  const median = quantile(values, 0.5);
  const q3 = quantile(values, 0.75);
  const max = values[values.length - 1];
  const scale = (value: number) => 40 + ((value - min) / (max - min || 1)) * 520;

  return (
    <div className="grid gap-4">
      <svg viewBox="0 0 600 150" className="h-[220px] w-full">
        <line x1={scale(min)} x2={scale(max)} y1={76} y2={76} stroke="#64748b" strokeWidth={3} />
        <line x1={scale(min)} x2={scale(min)} y1={58} y2={94} stroke="#64748b" strokeWidth={3} />
        <line x1={scale(max)} x2={scale(max)} y1={58} y2={94} stroke="#64748b" strokeWidth={3} />
        <rect x={scale(q1)} y={46} width={Math.max(2, scale(q3) - scale(q1))} height={60} rx={8} fill="#dbeafe" stroke="#2563eb" />
        <line x1={scale(median)} x2={scale(median)} y1={42} y2={110} stroke="#1d4ed8" strokeWidth={4} />
      </svg>
      <div className="grid grid-cols-5 gap-2 text-xs text-gray-600">
        <Stat label="Min" value={min} />
        <Stat label="Q1" value={q1} />
        <Stat label="Median" value={median} />
        <Stat label="Q3" value={q3} />
        <Stat label="Max" value={max} />
      </div>
    </div>
  );
}

function LocalCorrelation({ dataset, samplePct }: { dataset: LocalDataset; samplePct: number }) {
  const matrix = cachedCorrelationMatrix(dataset, samplePct);
  const numericColumns = matrix.columns;
  if (numericColumns.length < 2) {
    return <div className="text-sm text-gray-500">Need at least two numeric columns to compute local correlations.</div>;
  }

  return (
    <div className="max-h-[660px] overflow-auto rounded-xl bg-slate-50 p-3">
      <table className="text-xs">
        <thead>
          <tr>
            <th className="p-2 text-left text-gray-500">Feature</th>
            {numericColumns.map((column) => (
              <th key={column} className="p-2 text-left text-gray-500">{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {numericColumns.map((rowColumn) => (
            <tr key={rowColumn}>
              <th className="p-2 text-left font-medium">{rowColumn}</th>
              {numericColumns.map((column, columnIndex) => {
                const rowIndex = numericColumns.indexOf(rowColumn);
                const value = matrix.values[rowIndex]?.[columnIndex] ?? 0;
                const intensity = Math.round(Math.abs(value) * 180);
                return (
                  <td
                    key={column}
                    className="p-2 text-center font-medium"
                    style={{ background: `rgba(37, 99, 235, ${0.08 + intensity / 255})` }}
                  >
                    {value.toFixed(2)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LocalPairwisePlot({ dataset, samplePct }: { dataset: LocalDataset; samplePct: number }) {
  const rows = sampledRows(dataset, samplePct);
  const features = dataset.headers
    .map((header) => ({ header, values: numericValues(dataset, header, samplePct) }))
    .filter((item) => item.values.length >= 10)
    .sort((a, b) => variance(b.values) - variance(a.values))
    .slice(0, 4)
    .map((item) => item.header);
  if (features.length < 2) {
    return <div className="text-sm text-gray-500">Need at least two numeric features for pairwise plots.</div>;
  }
  return <PairwiseSvg rows={rows} features={features} />;
}

function variance(values: number[]) {
  if (values.length < 2) return 0;
  const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
  return values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / (values.length - 1);
}

function DatasetProfile({ columns, target, dataset }: { columns: ColumnInfo[]; target: string; dataset: LocalDataset | null }) {
  const numeric = columns.filter((column) => /int|float|double|number|numeric/i.test(column.dtype ?? "")).length;
  const totalRows = dataset?.rows.length ?? 0;
  return (
    <div className="grid grid-cols-2 gap-3 text-sm">
      <StatTile label="Rows" value={totalRows ? totalRows.toLocaleString() : "-"} />
      <StatTile label="Columns" value={String(columns.length || "-")} />
      <StatTile label="Numeric" value={String(numeric || "-")} />
      <StatTile label="Target" value={target || "-"} />
    </div>
  );
}

function MissingnessSnapshot({ dataset, columns }: { dataset: LocalDataset | null; columns: ColumnInfo[] }) {
  if (!dataset?.rows.length) {
    return <div className="text-sm text-gray-500">Missingness snapshot is available after loading a dataset.</div>;
  }
  const rows = columns
    .map((column) => {
      const missing = dataset.rows.filter((row) => row[column.name] === null || row[column.name] === undefined || row[column.name] === "").length;
      return { feature: column.name, pct: (missing / dataset.rows.length) * 100 };
    })
    .sort((a, b) => b.pct - a.pct)
    .slice(0, 10);
  return (
    <div className="space-y-2">
      {rows.map((row) => (
        <div key={row.feature} className="grid grid-cols-[180px_1fr_60px] items-center gap-3 text-xs">
          <div className="truncate font-medium text-gray-700">{row.feature}</div>
          <div className="h-2 rounded-full bg-gray-100">
            <div className="h-2 rounded-full bg-amber-500" style={{ width: `${Math.max(2, row.pct)}%` }} />
          </div>
          <div className="text-right text-gray-600">{row.pct.toFixed(1)}%</div>
        </div>
      ))}
    </div>
  );
}

function StatTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border bg-slate-50 p-3">
      <div className="text-xs font-medium text-gray-500">{label}</div>
      <div className="mt-1 truncate text-lg font-semibold text-gray-900">{value}</div>
    </div>
  );
}

function pearson(dataset: LocalDataset, a: string, b: string, samplePct: number) {
  const pairs = sampledRows(dataset, samplePct)
    .map((row) => [Number(row[a]), Number(row[b])])
    .filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y));
  if (pairs.length < 2) return 0;

  const meanX = pairs.reduce((sum, [x]) => sum + x, 0) / pairs.length;
  const meanY = pairs.reduce((sum, [, y]) => sum + y, 0) / pairs.length;
  const numerator = pairs.reduce((sum, [x, y]) => sum + (x - meanX) * (y - meanY), 0);
  const denominatorX = Math.sqrt(pairs.reduce((sum, [x]) => sum + (x - meanX) ** 2, 0));
  const denominatorY = Math.sqrt(pairs.reduce((sum, [, y]) => sum + (y - meanY) ** 2, 0));
  return numerator / (denominatorX * denominatorY || 1);
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded border bg-gray-50 p-2">
      <div className="font-semibold text-gray-500">{label}</div>
      <div className="mt-1 text-gray-900">{value.toFixed(3)}</div>
    </div>
  );
}
