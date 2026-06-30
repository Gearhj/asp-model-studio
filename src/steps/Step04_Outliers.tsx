// src/steps/Step04_Outliers.tsx
import React, { useMemo, useState, useCallback, useEffect } from "react";
import StepShell from "../components/StepShell";
import { useNavigate } from "react-router-dom";
import { logDecision } from "../lib/decisionJournal";
import { inferLocalColumns, loadLocalDataset } from "../lib/localDataset";

/**
 * Step 3: Outlier Analysis
 * - Robustly detects numeric features (dtype/type OR sample-based heuristic)
 * - Fetches sample from /api/data/get_sample
 * - Renders per-feature method selectors and before/after mini-histograms
 * - Bottom button -> /step04 (Missing Values)
 */

type MethodKey =
  | "IQR_1_5"
  | "IQR_3_0"
  | "ZSCORE_3"
  | "ZSCORE_4"
  | "PCT_01_99"
  | "PCT_05_95";

const METHOD_OPTIONS: { key: MethodKey; label: string }[] = [
  { key: "IQR_1_5", label: "1.5 IQR Method" },
  { key: "IQR_3_0", label: "3.0 IQR Method" },
  { key: "ZSCORE_3", label: "Z-Score Method (3σ)" },
  { key: "ZSCORE_4", label: "Z-Score Method (4σ)" },
  { key: "PCT_01_99", label: "Winsorize 0.5%/99.5%" },
  { key: "PCT_05_95", label: "Winsorize 5%/95%" },
];

const BASE =
  (import.meta.env?.VITE_API_BASE?.replace(/\/$/, "") as string) ||
  "http://127.0.0.1:8001/api";
const OUTLIER_CONFIG_KEY = "modeling-tool-outlier-methods";

// Colors
const COLOR_BEFORE = "#9CA3AF";
const COLOR_OUTLIER = "#EF4444";
const COLOR_AFTER = "#10B981";

/** ------------------------- Utils ------------------------- **/

type ColumnInfo = {
  name: string;
  dtype?: string;              // e.g., "float64", "int64", "object"
  role?: "feature" | "target";
  type?: string;               // sometimes "numeric", "categorical"
};

type SampleResp = {
  ok: boolean;
  headers: string[];
  rows: Array<Record<string, any>>;
  target?: string | null;
  selected_columns?: string[] | null;
};

function seeded(seed: string) {
  let s = 0;
  for (let i = 0; i < seed.length; i++) s = (s * 31 + seed.charCodeAt(i)) >>> 0;
  return () => {
    s ^= s << 13;
    s ^= s >>> 17;
    s ^= s << 5;
    return (s >>> 0) / 4294967295;
  };
}

function synthSeries(name: string, n = 1000): number[] {
  const rnd = seeded(name);
  const cfg: Record<string, { mu: number; sd: number; lo: number; hi: number }> = {
    transaction_amount: { mu: 350, sd: 120, lo: 0, hi: 1000 },
    account_age_days: { mu: 200, sd: 70, lo: 0, hi: 365 },
    num_previous_transactions: { mu: 16, sd: 6, lo: 0, hi: 50 },
    avg_transaction_amount: { mu: 220, sd: 90, lo: 0, hi: 600 },
    transaction_hour: { mu: 13, sd: 4, lo: 0, hi: 23 },
    days_since_last_transaction: { mu: 8, sd: 3, lo: 0, hi: 30 },
  };
  const c = cfg[name] ?? { mu: 0, sd: 1, lo: 0, hi: 1 };
  const boxMuller = () => {
    const u = Math.max(rnd(), 1e-12);
    const v = Math.max(rnd(), 1e-12);
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
  };
  const arr: number[] = [];
  for (let i = 0; i < n; i++) {
    const z = boxMuller();
    const val = Math.min(c.hi, Math.max(c.lo, c.mu + c.sd * z));
    arr.push(val);
  }
  for (let k = 0; k < Math.max(6, Math.floor(n * 0.01)); k++) {
    arr[Math.floor(rnd() * n)] = c.hi + (c.hi - c.lo) * 0.25 * rnd();
  }
  return arr;
}

function quantile(sorted: number[], p: number) {
  const idx = (sorted.length - 1) * p;
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  const h = idx - lo;
  return (1 - h) * sorted[lo] + h * sorted[hi];
}

function outlierThresholds(values: number[], method: MethodKey) {
  const s = [...values].sort((a, b) => a - b);
  const mean = s.reduce((acc, v) => acc + v, 0) / (s.length || 1);
  const sd = Math.sqrt(
    s.reduce((acc, v) => acc + (v - mean) * (v - mean), 0) / Math.max(1, s.length - 1)
  );

  if (method === "ZSCORE_3") return { lo: mean - 3 * sd, hi: mean + 3 * sd };
  if (method === "ZSCORE_4") return { lo: mean - 4 * sd, hi: mean + 4 * sd };
  if (method === "PCT_05_95") return { lo: quantile(s, 0.05), hi: quantile(s, 0.95) };
  if (method === "PCT_01_99") return { lo: quantile(s, 0.005), hi: quantile(s, 0.995) };

  const q1 = quantile(s, 0.25);
  const q3 = quantile(s, 0.75);
  const iqr = q3 - q1;
  const k = method === "IQR_3_0" ? 3.0 : 1.5;
  return { lo: q1 - k * iqr, hi: q3 + k * iqr };
}

function capValues(values: number[], lo: number, hi: number) {
  return values.map((v) => (v < lo ? lo : v > hi ? hi : v));
}

function countOutliers(values: number[], lo: number, hi: number) {
  let c = 0;
  for (const v of values) if (v < lo || v > hi) c++;
  return c;
}

function buildOutlierData(allCols: ColumnInfo[], rows: Array<Record<string, any>>, headers: string[], targetName: string) {
  const fromMeta = new Set(
    allCols
      .filter((c) => {
        if (!c?.name) return false;
        if (c.name === targetName) return false;
        const d = `${c.dtype ?? ""}`.toLowerCase();
        const t = `${c.type ?? ""}`.toLowerCase();
        return /int|float|double|decimal|number|numeric/.test(d) || /numeric/.test(t);
      })
      .map((c) => c.name)
  );

  const heuristic = new Set<string>();
  if (headers.length && rows.length) {
    const N = Math.min(rows.length, 2000);
    for (const h of headers) {
      if (!h || h === targetName) continue;
      let numericCount = 0;
      let seen = 0;
      for (let i = 0; i < N; i++) {
        const v = rows[i]?.[h];
        if (v === null || v === undefined || v === "") continue;
        seen++;
        const num = typeof v === "number" ? v : typeof v === "string" ? Number(v) : NaN;
        if (Number.isFinite(num)) numericCount++;
      }
      if (seen > 0 && numericCount / seen >= 0.8) {
        heuristic.add(h);
      }
    }
  }

  const final = Array.from(new Set([...fromMeta, ...heuristic]));
  const series: Record<string, number[]> = {};
  for (const f of final) {
    const vals: number[] = [];
    for (const r of rows) {
      const v = r?.[f];
      const num = typeof v === "number" ? v : v == null ? NaN : Number(v);
      if (Number.isFinite(num)) vals.push(num);
    }
    series[f] = vals;
  }

  return { final, series };
}

function informationValue(values: number[], rows: Array<Record<string, any>>, feature: string, targetName: string) {
  if (!targetName || !rows.length || !values.length) return 0;
  const targetValues = rows
    .map((row) => row?.[targetName])
    .filter((value) => value !== null && value !== undefined && value !== "");
  const uniqueTargets = Array.from(new Set(targetValues.map((value) => String(value))));
  if (uniqueTargets.length !== 2) return 0;
  const eventValue = uniqueTargets.sort()[uniqueTargets.length - 1];
  const paired = rows
    .map((row) => ({ x: Number(row?.[feature]), y: String(row?.[targetName]) === eventValue ? 1 : 0 }))
    .filter((row) => Number.isFinite(row.x));
  if (paired.length < 10) return 0;

  const sortedValues = paired.map((row) => row.x).sort((a, b) => a - b);
  const edges = Array.from(new Set([0, 0.2, 0.4, 0.6, 0.8, 1].map((p) => quantile(sortedValues, p))));
  if (edges.length < 3) return 0;
  const totalEvents = paired.reduce((sum, row) => sum + row.y, 0);
  const totalNonEvents = paired.length - totalEvents;
  if (!totalEvents || !totalNonEvents) return 0;

  let iv = 0;
  for (let i = 0; i < edges.length - 1; i++) {
    const lo = edges[i];
    const hi = edges[i + 1];
    const bucket = paired.filter((row) => (i === edges.length - 2 ? row.x >= lo && row.x <= hi : row.x >= lo && row.x < hi));
    const events = bucket.reduce((sum, row) => sum + row.y, 0);
    const nonEvents = bucket.length - events;
    const eventRate = Math.max(events / totalEvents, 1e-6);
    const nonEventRate = Math.max(nonEvents / totalNonEvents, 1e-6);
    iv += (eventRate - nonEventRate) * Math.log(eventRate / nonEventRate);
  }
  return Number.isFinite(iv) ? iv : 0;
}

type HistBin = { x0: number; x1: number; n: number; isOutlier?: boolean };

function makeBins(values: number[], nbins = 24, lo?: number, hi?: number): HistBin[] {
  if (!values.length) return [];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const a = Math.min(min, lo ?? min);
  const b = Math.max(max, hi ?? max);
  const w = (b - a) / (nbins || 1);
  const bins: HistBin[] = new Array(Math.max(1, nbins)).fill(0).map((_, i) => ({
    x0: a + i * w,
    x1: a + (i + 1) * w,
    n: 0,
  }));
  for (const v of values) {
    const idx = Math.max(0, Math.min(bins.length - 1, Math.floor((v - a) / (w || 1))));
    bins[idx].n += 1;
  }
  if (lo !== undefined && hi !== undefined) {
    for (const bin of bins) {
      if (bin.x1 < lo || bin.x0 > hi) bin.isOutlier = true;
    }
  }
  return bins;
}

/** ------------------------- UI bits ------------------------- **/

function MiniHist({
  title,
  values,
  thresholds,
  afterCap = false,
}: {
  title: string;
  values: number[];
  thresholds?: { lo: number; hi: number };
  afterCap?: boolean;
}) {
  const W = 300;
  const H = 120;
  const PL = 30,
    PR = 10,
    PT = 10,
    PB = 22;
  const w = W - PL - PR;
  const h = H - PT - PB;

  const bins = useMemo(() => {
    if (!values?.length) return [];
    if (afterCap && thresholds) {
      return makeBins(capValues(values, thresholds.lo, thresholds.hi), 24);
    }
    return makeBins(values, 24, thresholds?.lo, thresholds?.hi);
  }, [values, thresholds, afterCap]);

  const maxN = useMemo(() => Math.max(1, ...bins.map((b) => b.n)), [bins]);

  if (!bins.length) {
    return (
      <div className="rounded-md bg-white border border-gray-200 p-2">
        <div className="text-[10px] font-semibold text-gray-700 mb-1">{title}</div>
        <div className="text-[11px] text-gray-500">No data available</div>
      </div>
    );
  }

  const a = bins[0].x0;
  const b = bins[bins.length - 1].x1;
  const toX = (v: number) => PL + ((v - a) / (b - a || 1)) * w;
  const toY = (n: number) => PT + h - (n / (maxN || 1)) * h;

  return (
    <div className="rounded-md bg-white border border-gray-200 p-2">
      <div className="text-[10px] font-semibold text-gray-700 mb-1">{title}</div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
        <rect x="0" y="0" width={W} height={H} fill="#F9FAFB" />
        <line x1={PL} y1={PT + h} x2={PL + w} y2={PT + h} stroke="#D1D5DB" strokeWidth="1" />
        {bins.map((b, i) => {
          const x0 = toX(b.x0) + 0.7;
          const x1 = toX(b.x1) - 0.7;
          const barW = Math.max(1, x1 - x0);
          const y = toY(b.n);
          const color = afterCap ? COLOR_AFTER : b.isOutlier ? COLOR_OUTLIER : COLOR_BEFORE;
          return (
            <rect
              key={i}
              x={x0}
              y={y}
              width={barW}
              height={PT + h - y}
              fill={color}
              opacity={afterCap ? 0.9 : b.isOutlier ? 0.85 : 0.9}
            />
          );
        })}
        {thresholds && !afterCap && (
          <>
            <line
              x1={toX(thresholds.lo)}
              x2={toX(thresholds.lo)}
              y1={PT}
              y2={PT + h}
              stroke={COLOR_OUTLIER}
              strokeDasharray="3 3"
              strokeWidth="1"
            />
            <line
              x1={toX(thresholds.hi)}
              x2={toX(thresholds.hi)}
              y1={PT}
              y2={PT + h}
              stroke={COLOR_OUTLIER}
              strokeDasharray="3 3"
              strokeWidth="1"
            />
          </>
        )}
      </svg>
    </div>
  );
}

function FeaturePreview({
  feature,
  method,
  series,
}: {
  feature: string;
  method: MethodKey;
  series: number[];
}) {
  const values = useMemo(
    () => (series?.length ? series : synthSeries(feature, 1200)),
    [feature, series]
  );
  const thr = useMemo(() => outlierThresholds(values, method), [values, method]);
  const outCount = useMemo(() => countOutliers(values, thr.lo, thr.hi), [values, thr]);

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4">
      <div className="text-xs font-semibold uppercase text-gray-700 mb-2">
        {feature.toUpperCase()}
      </div>
      <div className="grid grid-cols-2 gap-3">
        <MiniHist title="Before Treatment" values={values} thresholds={thr} />
        <MiniHist title="After Capping" values={values} thresholds={thr} afterCap />
      </div>
      <div className="text-[11px] text-gray-600 mt-2">
        <span className="font-medium text-gray-800">Outliers flagged:</span>{" "}
        <span className="text-red-600 font-semibold">{outCount}</span>{" "}
        with{" "}
        <span className="font-medium">
          {METHOD_OPTIONS.find((o) => o.key === method)?.label}
        </span>
      </div>
    </div>
  );
}

/** ------------------------- Page ------------------------- **/

export default function Step04_Outliers() {
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [numericFeatures, setNumericFeatures] = useState<string[]>([]);
  const [seriesMap, setSeriesMap] = useState<Record<string, number[]>>({});
  const [methodByFeature, setMethodByFeature] = useState<Record<string, MethodKey>>({});
  const [globalMethod, setGlobalMethod] = useState<MethodKey>("IQR_1_5");
  const [featureIv, setFeatureIv] = useState<Record<string, number>>({});
  const [featurePage, setFeaturePage] = useState(0);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(OUTLIER_CONFIG_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw) as Record<string, MethodKey>;
      if (parsed && typeof parsed === "object") {
        setMethodByFeature(parsed);
      }
    } catch {
      // Ignore bad local state.
    }
  }, []);

  useEffect(() => {
    localStorage.setItem(OUTLIER_CONFIG_KEY, JSON.stringify(methodByFeature));
  }, [methodByFeature]);

  useEffect(() => {
    const controller = new AbortController();
    let mounted = true;

    async function load() {
      try {
        setLoading(true);

        // 1) Fetch columns
        const colsRes = await fetch(`${BASE}/columns`, { signal: controller.signal });
        const colsJson = (await colsRes.json()) as { ok?: boolean; columns?: ColumnInfo[] };
        const allCols: ColumnInfo[] = Array.isArray(colsJson?.columns) ? colsJson.columns : [];

        // 2) Fetch sample
        const sampleRes = await fetch(`${BASE}/data/get_sample`, { signal: controller.signal });
        const sampleJson = (await sampleRes.json()) as SampleResp;

        const rows = Array.isArray(sampleJson?.rows) ? sampleJson.rows : [];
        const headers = Array.isArray(sampleJson?.headers) ? sampleJson.headers : [];
        const targetName = (sampleJson?.target || allCols.find(c => c.role === "target")?.name || "") as string;

        let { final, series } = buildOutlierData(allCols, rows, headers, targetName);
        let ivMap: Record<string, number> = {};
        final.forEach((feature) => {
          ivMap[feature] = informationValue(series[feature] ?? [], rows, feature, targetName);
        });
        if (!final.length) {
          const localDataset = loadLocalDataset();
          if (localDataset?.headers.length) {
            const localColumns = inferLocalColumns(localDataset);
            const local = buildOutlierData(
              localColumns,
              localDataset.rows,
              localDataset.headers,
              localDataset.target ?? ""
            );
            final = local.final;
            series = local.series;
            ivMap = {};
            final.forEach((feature) => {
              ivMap[feature] = informationValue(local.series[feature] ?? [], localDataset.rows, feature, localDataset.target ?? "");
            });
          }
        }

        if (!mounted) return;
        const ordered = [...final].sort((a, b) => (ivMap[b] ?? 0) - (ivMap[a] ?? 0));
        setNumericFeatures(ordered);
        setSeriesMap(series);
        setFeatureIv(ivMap);
        setFeaturePage(0);
        setMethodByFeature((prev) => {
          const next: Record<string, MethodKey> = { ...prev };
          for (const f of final) if (!next[f]) next[f] = "IQR_1_5";
          for (const k of Object.keys(next)) if (!final.includes(k)) delete next[k];
          return next;
        });
      } catch (e) {
        if (!(e instanceof DOMException && e.name === "AbortError")) {
          console.error("Outliers load error:", e);
          const localDataset = loadLocalDataset();
          if (localDataset?.headers.length) {
            const localColumns = inferLocalColumns(localDataset);
            const { final, series } = buildOutlierData(
              localColumns,
              localDataset.rows,
              localDataset.headers,
              localDataset.target ?? ""
            );
            if (!mounted) return;
            const ivMap: Record<string, number> = {};
            final.forEach((feature) => {
              ivMap[feature] = informationValue(series[feature] ?? [], localDataset.rows, feature, localDataset.target ?? "");
            });
            const ordered = [...final].sort((a, b) => (ivMap[b] ?? 0) - (ivMap[a] ?? 0));
            setNumericFeatures(ordered);
            setSeriesMap(series);
            setFeatureIv(ivMap);
            setFeaturePage(0);
            setMethodByFeature((prev) => {
              const next: Record<string, MethodKey> = { ...prev };
              for (const f of final) if (!next[f]) next[f] = "IQR_1_5";
              for (const k of Object.keys(next)) if (!final.includes(k)) delete next[k];
              return next;
            });
          } else {
            setNumericFeatures([]);
            setSeriesMap({});
          }
        }
      } finally {
        if (mounted) setLoading(false);
      }
    }

    load();
    return () => {
      mounted = false;
      controller.abort();
    };
  }, []);

  const tableData = useMemo(() => {
    return numericFeatures.map((f) => {
      const s = seriesMap[f] ?? [];
      const values = s.length ? s : synthSeries(f, 1500);
      const thr = outlierThresholds(values, methodByFeature[f] || "IQR_1_5");
      const n = countOutliers(values, thr.lo, thr.hi);
      return { feature: f, outliers: n, method: methodByFeature[f] || "IQR_1_5", iv: featureIv[f] ?? 0 };
    });
  }, [numericFeatures, seriesMap, methodByFeature, featureIv]);

  const pageSize = 20;
  const pageCount = Math.max(1, Math.ceil(tableData.length / pageSize));
  const currentPage = Math.min(featurePage, pageCount - 1);
  const pagedTableData = tableData.slice(currentPage * pageSize, currentPage * pageSize + pageSize);
  const pagedFeatures = numericFeatures.slice(currentPage * pageSize, currentPage * pageSize + pageSize);

  const handleChange = useCallback((feature: string, key: MethodKey) => {
    logDecision({
      workflowStep: "Outlier Analysis",
      actionType: "outlier_method_selected",
      subject: feature,
      previousValue: methodByFeature[feature],
      newValue: key,
    });
    setMethodByFeature((prev) => ({ ...prev, [feature]: key }));
  }, [methodByFeature]);

  const applyGlobalMethod = useCallback(() => {
    logDecision({
      workflowStep: "Outlier Analysis",
      actionType: "outlier_method_selected",
      subject: "All numeric features",
      previousValue: methodByFeature,
      newValue: globalMethod,
    });
    setMethodByFeature((prev) => {
      const next: Record<string, MethodKey> = { ...prev };
      numericFeatures.forEach((feature) => {
        next[feature] = globalMethod;
      });
      return next;
    });
  }, [globalMethod, numericFeatures, methodByFeature]);

  return (
    <StepShell
      title="Step 3: Outlier Analysis"
      subtitle="Identify and handle outliers in numeric features"
      nextPath="/step04"   // navigate to Missing Values
    >
      {/* Methods table */}
      <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">
          Outlier Detection Methods
        </h3>

        {numericFeatures.length > 0 && (
          <div className="mb-5 flex flex-wrap items-end gap-3 rounded-lg border border-gray-200 bg-gray-50 p-3">
            <label className="grid gap-1">
              <span className="text-xs font-medium text-gray-600">Global method</span>
              <select
                value={globalMethod}
                onChange={(e) => setGlobalMethod(e.target.value as MethodKey)}
                className="w-64 rounded-lg border border-gray-300 bg-white p-2 text-sm"
              >
                {METHOD_OPTIONS.map((opt) => (
                  <option key={opt.key} value={opt.key}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              onClick={applyGlobalMethod}
              className="rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-indigo-700"
            >
              Apply to All Features
            </button>
            <div className="text-xs text-gray-500">
              Use this for a default policy, then override individual features below.
            </div>
          </div>
        )}

        {loading ? (
          <div className="text-sm text-gray-600">Loading features…</div>
        ) : numericFeatures.length === 0 ? (
          <div className="text-sm text-gray-600">
            No numeric features found. Make sure Step 1 loaded a CSV with numeric columns, then refresh this page.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left text-gray-600">
                  <th className="py-2 px-3">Feature</th>
                  <th className="py-2 px-3">Outliers Detected</th>
                  <th className="py-2 px-3">IV</th>
                  <th className="py-2 px-3">Method</th>
                </tr>
              </thead>
              <tbody>
                {pagedTableData.map((row) => (
                  <tr key={row.feature} className="border-t border-gray-100">
                    <td className="py-2 px-3 font-medium text-gray-800">{row.feature}</td>
                    <td className="py-2 px-3">
                      <span className="text-red-600 font-semibold">{row.outliers}</span>
                    </td>
                    <td className="py-2 px-3 text-gray-700">{row.iv.toFixed(4)}</td>
                    <td className="py-2 px-3">
                      <select
                        value={methodByFeature[row.feature]}
                        onChange={(e) => handleChange(row.feature, e.target.value as MethodKey)}
                        className="w-56 p-2 border border-gray-300 rounded-lg"
                      >
                        {METHOD_OPTIONS.map((opt) => (
                          <option key={opt.key} value={opt.key}>
                            {opt.label}
                          </option>
                        ))}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-xs text-gray-600">
              <div>
                Showing {currentPage * pageSize + 1}-{Math.min((currentPage + 1) * pageSize, tableData.length)} of {tableData.length} features, sorted by IV.
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={currentPage === 0}
                  onClick={() => setFeaturePage((page) => Math.max(0, page - 1))}
                  className="rounded-md border px-3 py-1 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Previous 20
                </button>
                <span>Page {currentPage + 1} of {pageCount}</span>
                <button
                  type="button"
                  disabled={currentPage >= pageCount - 1}
                  onClick={() => setFeaturePage((page) => Math.min(pageCount - 1, page + 1))}
                  className="rounded-md border px-3 py-1 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Next 20
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Per-feature previews */}
      <div className="grid xl:grid-cols-3 md:grid-cols-2 gap-6">
        {pagedFeatures.map((f) => (
          <FeaturePreview
            key={f}
            feature={f}
            method={methodByFeature[f] || "IQR_1_5"}
            series={seriesMap[f] || []}
          />
        ))}
      </div>

      <div className="mt-6 text-xs text-gray-500">
        <p className="mb-1">
          <span className="font-semibold">Note:</span> Each dropdown controls only its feature.
          If you later call a backend service to apply capping, pass the chosen method for each
          feature so the server uses the correct thresholds.
        </p>
      </div>
    </StepShell>
  );
}
