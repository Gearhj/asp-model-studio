// src/steps/Step02_EDA.tsx
import React, { useEffect, useMemo, useState } from "react";
import ErrorBoundary from "../components/ErrorBoundary";
import D3HistogramStackedGrouped from "../components/D3HistogramStackedGrouped";
import D3Boxplot from "../components/D3Boxplot";
import D3Heatmap from "../components/D3Heatmap";
import D3Pairplot from "../components/D3Pairplot";
import { PairwiseSvg } from "../components/D3Pairplot";
import { useNavigate } from "react-router-dom";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { inferLocalColumns, loadLocalDataset, type LocalDataset } from "../lib/localDataset";

type ColumnInfo = { name: string; dtype?: string; role?: "feature" | "target" };

const BASE =
  (import.meta as any)?.env?.VITE_API_BASE?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

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
  const [usingLocalDataset, setUsingLocalDataset] = useState(false);
  const [localDataset, setLocalDataset] = useState<LocalDataset | null>(null);

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
          if (!cols.length) {
            cols = inferLocalColumns(cachedDataset);
            backendTarget = cachedDataset.target ?? "";
          }
        } else {
          setUsingLocalDataset(false);
          setLocalDataset(null);
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

      {/* Bottom nav */}
      <div className="mt-8 flex flex-col items-center gap-3">
        <button
          className="px-4 py-2 rounded bg-indigo-600 text-white hover:bg-indigo-700"
          onClick={() => {
            markComplete("step02");
            navigate("/step03");
          }}
        >
          Mark Complete & Next Step
        </button>
      </div>
    </div>
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
  const pad = 34;
  const barWidth = (chartWidth - pad * 2) / bucketCount;

  return (
    <svg viewBox={`0 0 ${chartWidth} ${chartHeight}`} className="h-[320px] w-full">
      <line x1={pad} y1={chartHeight - pad} x2={chartWidth - pad} y2={chartHeight - pad} stroke="#d1d5db" />
      {counts.map((count, index) => {
        const height = ((chartHeight - pad * 2) * count) / maxCount;
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
      <text x={pad} y={chartHeight - 8} fontSize="12" fill="#475569">
        {min.toFixed(2)}
      </text>
      <text x={chartWidth - pad} y={chartHeight - 8} textAnchor="end" fontSize="12" fill="#475569">
        {max.toFixed(2)}
      </text>
    </svg>
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
  const numericColumns = dataset.headers.filter((header) => numericValues(dataset, header, samplePct).length >= 3).slice(0, 20);
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
              {numericColumns.map((column) => {
                const value = pearson(dataset, rowColumn, column, samplePct);
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
