import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useWorkflowStore } from "../state/useWorkflowStore";

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

type RankedRow = { key: string; name: string; auc?: number; pr_auc?: number };
type ImportanceRow = { feature: string; importance: number; source?: string; direction?: number };
type DetailResponse = {
  ok: boolean;
  kind?: "equation" | "tree" | "generic";
  intercept?: number;
  coefficients?: { feature: string; coefficient: number; odds_ratio: number }[];
  tree_text?: string;
  message?: string;
  error?: string;
};
type CurveRow = { value: string | number; label?: string; prediction: number };
type SensitivityRow = { scenario: string; prediction: number; delta: number };
type RfeRow = { feature: string; selected: boolean; rank: number; importance?: number };
type HyperparameterRow = { parameter: string; value: string };
type RfeCurveRow = {
  feature_count: number;
  auc: number;
  display_auc?: number;
  marginal_auc: number | null;
  added_feature: string;
  features: string[];
};
type BoundaryPoint = { x: number; y: number; class: number };
type BoundaryCell = { x: number; y: number; score: number };
type BoundaryResponse = {
  ok: boolean;
  error?: string;
  x_feature?: string;
  y_feature?: string;
  x_domain?: [number, number];
  y_domain?: [number, number];
  resolution?: number;
  grid?: BoundaryCell[];
  points?: BoundaryPoint[];
  numeric_features?: string[];
};

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Request failed (${res.status})`);
  return (await res.json()) as T;
}

export default function Step09_Interpretation() {
  const navigate = useNavigate();
  const markComplete = useWorkflowStore((state) => state.markComplete);
  const [models, setModels] = useState<RankedRow[]>([]);
  const [selectedModel, setSelectedModel] = useState("");
  const [selectedFeature, setSelectedFeature] = useState("");
  const [importance, setImportance] = useState<ImportanceRow[]>([]);
  const [details, setDetails] = useState<DetailResponse | null>(null);
  const [hyperparameters, setHyperparameters] = useState<HyperparameterRow[]>([]);
  const [pdp, setPdp] = useState<CurveRow[]>([]);
  const [sensitivity, setSensitivity] = useState<SensitivityRow[]>([]);
  const [shapRows, setShapRows] = useState<ImportanceRow[]>([]);
  const [rfeKeep, setRfeKeep] = useState(10);
  const [rfeRows, setRfeRows] = useState<RfeRow[]>([]);
  const [rfeCurve, setRfeCurve] = useState<RfeCurveRow[]>([]);
  const [rfeRunning, setRfeRunning] = useState(false);
  const [recommendedCount, setRecommendedCount] = useState<number | null>(null);
  const [boundary, setBoundary] = useState<BoundaryResponse | null>(null);
  const [boundaryX, setBoundaryX] = useState("");
  const [boundaryY, setBoundaryY] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    getJson<{ ok: boolean; summary?: { ranked?: RankedRow[] } }>(`${API_BASE}/train/last`)
      .then((data) => {
        const ranked = data.summary?.ranked ?? [];
        setModels(ranked);
        setSelectedModel(ranked[0]?.key ?? "");
      })
      .catch((err) => setMessage(String(err?.message ?? err)));
  }, []);

  useEffect(() => {
    if (!selectedModel) return;
    setMessage("");
    Promise.all([
      getJson<{ ok: boolean; rows?: ImportanceRow[]; error?: string }>(
        `${API_BASE}/interpretation/importance?model=${encodeURIComponent(selectedModel)}`
      ),
      getJson<DetailResponse>(
        `${API_BASE}/interpretation/details?model=${encodeURIComponent(selectedModel)}`
      ),
      getJson<{ ok: boolean; rows?: HyperparameterRow[] }>(
        `${API_BASE}/interpretation/hyperparameters?model=${encodeURIComponent(selectedModel)}`
      ),
      getJson<{ ok: boolean; rows?: ImportanceRow[]; method?: string }>(
        `${API_BASE}/interpretation/shap?model=${encodeURIComponent(selectedModel)}`
      ),
    ])
      .then(([importanceRes, detailsRes, hyperparameterRes, shapRes]) => {
        const rows = importanceRes.rows ?? [];
        setImportance(rows);
        setDetails(detailsRes);
        setHyperparameters(hyperparameterRes.rows ?? []);
        setShapRows(shapRes.rows ?? []);
        setSelectedFeature(rows[0]?.feature?.replace(/^.*__/, "") || "");
        setRfeRows([]);
        setRfeCurve([]);
        setRecommendedCount(null);
      })
      .catch((err) => setMessage(String(err?.message ?? err)));
  }, [selectedModel]);

  useEffect(() => {
    if (!selectedModel || !selectedFeature) return;
    Promise.all([
      getJson<{ ok: boolean; rows?: CurveRow[] }>(
        `${API_BASE}/interpretation/pdp?model=${encodeURIComponent(selectedModel)}&feature=${encodeURIComponent(selectedFeature)}`
      ),
      getJson<{ ok: boolean; rows?: SensitivityRow[] }>(
        `${API_BASE}/interpretation/sensitivity?model=${encodeURIComponent(selectedModel)}&feature=${encodeURIComponent(selectedFeature)}`
      ),
    ])
      .then(([pdpRes, sensitivityRes]) => {
        setPdp(pdpRes.rows ?? []);
        setSensitivity(sensitivityRes.rows ?? []);
      })
      .catch((err) => setMessage(String(err?.message ?? err)));
  }, [selectedModel, selectedFeature]);

  useEffect(() => {
    if (!selectedModel) return;
    const params = new URLSearchParams({ model: selectedModel });
    if (boundaryX) params.set("x_feature", boundaryX);
    if (boundaryY) params.set("y_feature", boundaryY);
    getJson<BoundaryResponse>(`${API_BASE}/interpretation/decision_boundary?${params.toString()}`)
      .then((data) => {
        if (!data.ok) {
          setBoundary(data);
          return;
        }
        setBoundary(data);
        setBoundaryX(data.x_feature ?? "");
        setBoundaryY(data.y_feature ?? "");
      })
      .catch((err) => setMessage(String(err?.message ?? err)));
  }, [selectedModel, boundaryX, boundaryY]);

  const featureOptions = useMemo(
    () => Array.from(new Set(importance.map((row) => row.feature.replace(/^.*__/, "")))),
    [importance]
  );

  const runRfe = () => {
    setRfeRunning(true);
    setMessage("");
    getJson<{ ok: boolean; rows?: RfeRow[]; curve?: RfeCurveRow[]; recommended_count?: number; best_count?: number; error?: string }>(
      `${API_BASE}/interpretation/rfe?model=${encodeURIComponent(selectedModel)}&keep=${rfeKeep}`
    )
      .then((data) => {
        if (!data.ok) throw new Error(data.error ?? "RFE failed.");
        setRfeRows(data.rows ?? []);
        setRfeCurve(data.curve ?? []);
        setRecommendedCount(data.recommended_count ?? null);
        setRfeKeep(data.recommended_count ?? data.best_count ?? rfeKeep);
      })
      .catch((err) => setMessage(String(err?.message ?? err)))
      .finally(() => setRfeRunning(false));
  };

  if (!models.length) {
    return (
      <div className="max-w-[1100px] mx-auto space-y-4">
        <h1 className="text-2xl font-semibold">Step 9: Model Interpretation</h1>
        <div className="rounded-2xl border border-gray-200 bg-white p-4 text-sm text-gray-600">
          Train models first, then return here for interpretation.
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-[1200px] mx-auto space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Step 9: Model Interpretation</h1>
          <p className="mt-1 text-sm text-gray-600">
            Explain model behavior, feature effects, sensitivity, and candidate reduced feature sets.
          </p>
        </div>
        <label className="grid gap-1 text-sm">
          <span className="text-xs font-medium text-gray-600">Model</span>
          <select className="rounded-md border px-3 py-2" value={selectedModel} onChange={(e) => setSelectedModel(e.target.value)}>
            {models.map((model) => (
              <option key={model.key} value={model.key}>
                {model.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      {message && <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">{message}</div>}

      <section className="rounded-2xl border border-gray-200 bg-white p-4">
        <h2 className="text-sm font-semibold">Model-Specific Explanation</h2>
        <ModelDetails details={details} />
      </section>

      <section className="rounded-2xl border border-gray-200 bg-white p-4">
        <h2 className="text-sm font-semibold">Final Hyperparameter Settings</h2>
        <HyperparameterTable rows={hyperparameters} />
      </section>

      <section className="rounded-2xl border border-gray-200 bg-white p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">Decision Boundary</h2>
            <p className="mt-1 text-xs text-gray-500">Shows the selected model response across two numeric features while holding all other fields at typical values.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <select className="rounded-md border px-3 py-2 text-sm" value={boundaryX} onChange={(e) => setBoundaryX(e.target.value)}>
              {(boundary?.numeric_features ?? []).map((feature) => <option key={feature} value={feature}>{feature}</option>)}
            </select>
            <select className="rounded-md border px-3 py-2 text-sm" value={boundaryY} onChange={(e) => setBoundaryY(e.target.value)}>
              {(boundary?.numeric_features ?? []).filter((feature) => feature !== boundaryX).map((feature) => <option key={feature} value={feature}>{feature}</option>)}
            </select>
          </div>
        </div>
        <DecisionBoundaryChart boundary={boundary} />
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-2xl border border-gray-200 bg-white p-4">
          <h2 className="text-sm font-semibold">Feature Importance</h2>
          <BarTable rows={importance} valueKey="importance" />
        </section>
        <section className="rounded-2xl border border-gray-200 bg-white p-4">
          <h2 className="text-sm font-semibold">SHAP Summary</h2>
          <p className="mt-1 text-xs text-gray-500">Model-agnostic replacement impact on held-out predictions. This differs from native feature importance.</p>
          <BarTable rows={shapRows} valueKey="importance" />
        </section>
      </div>

      <section className="rounded-2xl border border-gray-200 bg-white p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">PDP / Sensitivity</h2>
            <p className="mt-1 text-xs text-gray-500">Select a feature to inspect marginal response and scenario sensitivity.</p>
          </div>
          <select className="rounded-md border px-3 py-2 text-sm" value={selectedFeature} onChange={(e) => setSelectedFeature(e.target.value)}>
            {featureOptions.map((feature) => (
              <option key={feature} value={feature}>{feature}</option>
            ))}
          </select>
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <LineChart title="Partial Dependence Plot" rows={pdp} feature={selectedFeature} />
          <SensitivityTable rows={sensitivity} />
        </div>
      </section>

      <section className="rounded-2xl border border-gray-200 bg-white p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">Recursive Feature Elimination</h2>
            <p className="mt-1 text-xs text-gray-500">Runs backward elimination and recommends a retained feature count from the AUC curve and marginal benefit.</p>
          </div>
          <div className="flex items-end gap-2">
            {recommendedCount && (
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-medium text-emerald-800">
                Recommended: {recommendedCount} features
              </div>
            )}
            <button
              className="rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:bg-indigo-300"
              disabled={rfeRunning}
              onClick={runRfe}
            >
              {rfeRunning ? "Running..." : "Run RFE"}
            </button>
          </div>
        </div>
        <RfeCurveChart rows={rfeCurve} selectedCount={rfeKeep} recommendedCount={recommendedCount} onSelectCount={setRfeKeep} />
        <RfeTable rows={rfeRows} selectedCount={rfeKeep} />
      </section>

      <div className="pb-10 flex justify-center">
        <button
          className="rounded-xl bg-indigo-600 px-5 py-3 text-white shadow-sm"
          onClick={() => {
            markComplete("step09");
            navigate("/dashboard");
          }}
        >
          Mark Complete & Return to Dashboard
        </button>
      </div>
    </div>
  );
}

function ModelDetails({ details }: { details: DetailResponse | null }) {
  if (!details) return <div className="mt-3 text-sm text-gray-500">Loading model details...</div>;
  if (!details.ok) return <div className="mt-3 text-sm text-rose-700">{details.error}</div>;
  if (details.kind === "equation") {
    return (
      <div className="mt-3">
        <div className="rounded-lg bg-slate-50 p-3 font-mono text-xs">logit(p) = {details.intercept?.toFixed(4)} + Σ(coef × feature)</div>
        <BarTable rows={(details.coefficients ?? []).map((row) => ({ feature: row.feature, importance: row.coefficient, source: `OR ${row.odds_ratio.toFixed(3)}` }))} valueKey="importance" />
      </div>
    );
  }
  if (details.kind === "tree") {
    return <pre className="mt-3 max-h-[360px] overflow-auto rounded-lg bg-slate-950 p-4 text-xs text-slate-100">{details.tree_text}</pre>;
  }
  return <div className="mt-3 text-sm text-gray-600">{details.message}</div>;
}

function BarTable({ rows, valueKey }: { rows: ImportanceRow[]; valueKey: "importance" }) {
  const top = rows.slice(0, 15);
  const max = Math.max(...top.map((row) => Math.abs(row[valueKey])), 1e-9);
  return (
    <div className="mt-3 space-y-2">
      {top.map((row) => (
        <div key={`${row.feature}-${row.source ?? ""}`} className="grid grid-cols-[180px_1fr_90px] items-center gap-3 text-xs">
          <div className="truncate font-medium text-gray-700">{row.feature}</div>
          <div className="h-2 rounded-full bg-gray-100">
            <div className="h-2 rounded-full bg-indigo-600" style={{ width: `${Math.max(3, (Math.abs(row[valueKey]) / max) * 100)}%` }} />
          </div>
          <div className="text-right text-gray-600">
            {row[valueKey].toFixed(4)}
            {typeof row.direction === "number" && row.direction !== 0 && (
              <span className={row.direction >= 0 ? "ml-1 text-emerald-600" : "ml-1 text-rose-600"}>
                {row.direction >= 0 ? "+" : "-"}
              </span>
            )}
          </div>
        </div>
      ))}
      {!top.length && <div className="text-sm text-gray-500">No importance data available.</div>}
    </div>
  );
}

function DecisionBoundaryChart({ boundary }: { boundary: BoundaryResponse | null }) {
  if (!boundary) return <div className="mt-3 rounded-xl bg-slate-50 p-4 text-sm text-gray-500">Loading decision boundary...</div>;
  if (!boundary.ok) return <div className="mt-3 rounded-xl bg-amber-50 p-4 text-sm text-amber-900">{boundary.error ?? "Decision boundary unavailable."}</div>;
  const grid = boundary.grid ?? [];
  const points = boundary.points ?? [];
  const [xMin, xMax] = boundary.x_domain ?? [0, 1];
  const [yMin, yMax] = boundary.y_domain ?? [0, 1];
  const width = 880;
  const height = 430;
  const pad = 54;
  const plotWidth = width - pad - 24;
  const plotHeight = height - pad - 24;
  const resolution = boundary.resolution ?? 60;
  const cellW = plotWidth / resolution + 0.5;
  const cellH = plotHeight / resolution + 0.5;
  const x = (value: number) => pad + ((value - xMin) / (xMax - xMin || 1)) * plotWidth;
  const y = (value: number) => 18 + ((yMax - value) / (yMax - yMin || 1)) * plotHeight;
  const color = (score: number) => {
    const clamped = Math.max(0, Math.min(1, score));
    const red = Math.round(248 * clamped + 239 * (1 - clamped));
    const green = Math.round(113 * clamped + 246 * (1 - clamped));
    const blue = Math.round(113 * clamped + 255 * (1 - clamped));
    return `rgb(${red},${green},${blue})`;
  };

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="mt-3 h-[430px] w-full rounded-xl bg-slate-50">
      {grid.map((cell, index) => (
        <rect
          key={index}
          x={x(cell.x) - cellW / 2}
          y={y(cell.y) - cellH / 2}
          width={cellW}
          height={cellH}
          fill={color(cell.score)}
          opacity={0.82}
        />
      ))}
      <line x1={pad} y1={height - pad} x2={width - 24} y2={height - pad} stroke="#94a3b8" />
      <line x1={pad} y1={18} x2={pad} y2={height - pad} stroke="#94a3b8" />
      {points.map((point, index) => (
        <circle
          key={index}
          cx={x(point.x)}
          cy={y(point.y)}
          r={3}
          fill={point.class ? "#111827" : "#ffffff"}
          stroke="#111827"
          strokeWidth={1}
          opacity={0.82}
        />
      ))}
      <text x={width / 2} y={height - 12} textAnchor="middle" className="fill-slate-700 text-[11px]">{boundary.x_feature}</text>
      <text x={16} y={height / 2} textAnchor="middle" transform={`rotate(-90 16 ${height / 2})`} className="fill-slate-700 text-[11px]">{boundary.y_feature}</text>
      <text x={pad} y={height - 34} className="fill-slate-500 text-[10px]">{xMin.toFixed(3)}</text>
      <text x={width - 24} y={height - 34} textAnchor="end" className="fill-slate-500 text-[10px]">{xMax.toFixed(3)}</text>
    </svg>
  );
}

function HyperparameterTable({ rows }: { rows: HyperparameterRow[] }) {
  if (!rows.length) {
    return <div className="mt-3 text-sm text-gray-500">No grid-search settings were recorded for this model. Default estimator settings are being used.</div>;
  }
  return (
    <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {rows.map((row) => (
        <div key={row.parameter} className="rounded-lg border border-gray-100 bg-slate-50 px-3 py-2">
          <div className="text-[11px] font-semibold uppercase text-gray-500">{row.parameter}</div>
          <div className="mt-1 truncate text-sm text-gray-900" title={row.value}>{row.value}</div>
        </div>
      ))}
    </div>
  );
}

function LineChart({ title, rows, feature }: { title: string; rows: CurveRow[]; feature: string }) {
  if (!rows.length) return <div className="text-sm text-gray-500">No PDP data available.</div>;
  const width = 520;
  const height = 260;
  const pad = 46;
  const values = rows.map((row) => row.prediction);
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const spread = Math.max(rawMax - rawMin, 0.001);
  const minY = Math.max(0, rawMin - spread * 0.2);
  const maxY = Math.min(1, rawMax + spread * 0.2);
  const plotWidth = width - pad - 18;
  const plotHeight = height - pad - 24;
  const x = (index: number) => pad + (index / Math.max(1, rows.length - 1)) * plotWidth;
  const y = (value: number) => 18 + ((maxY - value) / (maxY - minY || 1)) * plotHeight;
  const points = rows.map((row, index) => `${x(index)},${y(row.prediction)}`).join(" ");
  const first = rows[0];
  const last = rows[rows.length - 1];
  return (
    <div>
      <div className="mb-2 text-xs font-semibold text-gray-700">{title}</div>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-[260px] w-full rounded-xl bg-slate-50">
        <line x1={pad} y1={height - pad} x2={width - 18} y2={height - pad} stroke="#cbd5e1" />
        <line x1={pad} y1={18} x2={pad} y2={height - pad} stroke="#cbd5e1" />
        {[0, 0.5, 1].map((tick) => {
          const value = minY + (maxY - minY) * tick;
          const yy = y(value);
          return (
            <g key={tick}>
              <line x1={pad} y1={yy} x2={width - 18} y2={yy} stroke="#e2e8f0" />
              <text x={pad - 8} y={yy + 4} textAnchor="end" className="fill-slate-500 text-[10px]">
                {value.toFixed(3)}
              </text>
            </g>
          );
        })}
        <polyline fill="none" stroke="#4f46e5" strokeWidth="3" points={points} />
        {rows.map((row, index) => (
          <circle key={`${row.label ?? row.value}-${index}`} cx={x(index)} cy={y(row.prediction)} r={3} fill="#4f46e5" />
        ))}
        {first && <text x={pad} y={height - 12} className="fill-slate-500 text-[10px]">{first.label ?? first.value}</text>}
        {last && <text x={width - 18} y={height - 12} textAnchor="end" className="fill-slate-500 text-[10px]">{last.label ?? last.value}</text>}
        <text x={width / 2} y={height - 12} textAnchor="middle" className="fill-slate-600 text-[10px]">{feature}</text>
      </svg>
    </div>
  );
}

function RfeCurveChart({
  rows,
  selectedCount,
  recommendedCount,
  onSelectCount,
}: {
  rows: RfeCurveRow[];
  selectedCount: number;
  recommendedCount: number | null;
  onSelectCount: (count: number) => void;
}) {
  if (!rows.length) {
    return <div className="mt-4 rounded-xl bg-slate-50 p-4 text-sm text-gray-500">Run RFE to generate the AUC and marginal-benefit curve.</div>;
  }

  const width = 980;
  const height = 330;
  const pad = 52;
  const aucValues = rows.map((row) => row.display_auc ?? row.auc);
  const marginalValues = rows.map((row) => Math.max(0, row.marginal_auc ?? 0));
  const aucMin = Math.max(0, Math.min(...aucValues) - 0.015);
  const aucMax = Math.min(1, Math.max(...aucValues) + 0.015);
  const marginalMax = Math.max(...marginalValues, 0.001);
  const plotWidth = width - pad - 24;
  const plotHeight = height - pad - 28;
  const barSlot = plotWidth / rows.length;
  const barWidth = Math.max(6, Math.min(22, barSlot * 0.62));
  const x = (index: number) => pad + index * barSlot + barSlot / 2;
  const yAuc = (value: number) => 18 + ((aucMax - value) / (aucMax - aucMin || 1)) * plotHeight;
  const yMarginal = (value: number) => 18 + ((marginalMax - Math.max(0, value)) / marginalMax) * plotHeight;
  const marginalPoints = rows
    .map((row, index) => `${x(index)},${yMarginal(row.marginal_auc ?? 0)}`)
    .join(" ");

  return (
    <div className="mt-4 rounded-xl bg-slate-50 p-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs">
        <div className="font-semibold text-gray-700">RFE AUC by Feature Count</div>
        <div className="flex gap-3 text-gray-600">
          <span><span className="mr-1 inline-block h-2 w-3 rounded-sm bg-indigo-500" />AUC</span>
          <span><span className="mr-1 inline-block h-2 w-3 rounded-sm bg-emerald-500" />Marginal AUC</span>
          {recommendedCount && <span>Suggested elbow: {recommendedCount} features</span>}
        </div>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-[330px] w-full">
        <line x1={pad} y1={height - pad} x2={width - 24} y2={height - pad} stroke="#cbd5e1" />
        <line x1={pad} y1={18} x2={pad} y2={height - pad} stroke="#cbd5e1" />
        {[0, 0.5, 1].map((tick) => {
          const value = aucMin + (aucMax - aucMin) * tick;
          const yy = yAuc(value);
          return (
            <g key={tick}>
              <line x1={pad} y1={yy} x2={width - 24} y2={yy} stroke="#e2e8f0" />
              <text x={pad - 8} y={yy + 4} textAnchor="end" className="fill-slate-500 text-[10px]">{value.toFixed(3)}</text>
            </g>
          );
        })}
        {rows.map((row, index) => {
          const selected = row.feature_count === selectedCount;
          const chartAuc = row.display_auc ?? row.auc;
          const barHeight = height - pad - yAuc(chartAuc);
          return (
            <g key={row.feature_count} onClick={() => onSelectCount(row.feature_count)} className="cursor-pointer">
              <rect
                x={x(index) - barWidth / 2}
                y={yAuc(chartAuc)}
                width={barWidth}
                height={barHeight}
                rx={3}
                className={selected ? "fill-indigo-700" : "fill-indigo-500"}
              />
              {row.feature_count === recommendedCount && (
                <line x1={x(index)} y1={18} x2={x(index)} y2={height - pad} stroke="#10b981" strokeDasharray="4 4" />
              )}
              {index % Math.ceil(rows.length / 12) === 0 && (
                <text x={x(index)} y={height - 30} textAnchor="middle" className="fill-slate-500 text-[10px]">{row.feature_count}</text>
              )}
            </g>
          );
        })}
        <polyline fill="none" stroke="#10b981" strokeWidth="3" points={marginalPoints} />
        {rows.map((row, index) => (
          <circle key={`m-${row.feature_count}`} cx={x(index)} cy={yMarginal(row.marginal_auc ?? 0)} r={3} fill="#10b981" />
        ))}
        <text x={width / 2} y={height - 8} textAnchor="middle" className="fill-slate-600 text-[10px]">Number of features retained</text>
      </svg>
    </div>
  );
}

function SensitivityTable({ rows }: { rows: SensitivityRow[] }) {
  return (
    <div>
      <div className="mb-2 text-xs font-semibold text-gray-700">Sensitivity Analysis</div>
      <table className="w-full text-sm">
        <thead><tr className="text-left text-xs text-gray-500"><th className="py-1">Scenario</th><th>Prediction</th><th>Delta</th></tr></thead>
        <tbody>{rows.map((row) => <tr key={row.scenario} className="border-t"><td className="py-1">{row.scenario}</td><td>{row.prediction.toFixed(4)}</td><td className={row.delta >= 0 ? "text-emerald-700" : "text-rose-700"}>{row.delta.toFixed(4)}</td></tr>)}</tbody>
      </table>
    </div>
  );
}

function RfeTable({ rows, selectedCount }: { rows: RfeRow[]; selectedCount: number }) {
  if (!rows.length) return <div className="mt-3 text-sm text-gray-500">Run RFE to rank candidate features.</div>;
  return (
    <table className="mt-4 w-full text-sm">
      <thead><tr className="text-left text-xs text-gray-500"><th className="py-1">Feature</th><th>Selected</th><th>Rank</th><th>Importance</th></tr></thead>
      <tbody>{rows.map((row) => {
        const selected = row.rank <= selectedCount;
        return <tr key={row.feature} className="border-t"><td className="py-1">{row.feature}</td><td>{selected ? "Yes" : "No"}</td><td>{row.rank}</td><td>{typeof row.importance === "number" ? row.importance.toFixed(4) : "-"}</td></tr>;
      })}</tbody>
    </table>
  );
}
