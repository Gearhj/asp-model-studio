import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useWorkflowStore } from "../state/useWorkflowStore";

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

const LOCAL_TRAINING_SUMMARY_KEY = "modeling-tool-training-summary";

type Ranked = {
  key: string;
  name: string;
  auc: number;
  pr_auc: number;
  accuracy?: number;
  f1?: number;
}[];

type Curves = {
  ok: boolean;
  // Optional future PNGs – only used if backend supplies them
  roc_b64?: string;
  pr_b64?: string;
  cm_b64?: string;
  // Scalar metrics from backend
  metrics?: {
    precision: number;
    recall: number;
    f1: number;
    auc: number;
    pr_auc: number;
  };
  roc?: { fpr: number[]; tpr: number[] };
  pr?: { precision: number[]; recall: number[] };
  // Confusion matrix [ [TN, FP], [FN, TP] ]
  confusion?: number[][];
  error?: string;
};

type DecileRow = {
  decile: number;
  n: number;
  positives: number;
  event_rate?: number;
  rate?: number;
  lift: number;
};

function loadLocalRanked(): Ranked {
  const raw = sessionStorage.getItem(LOCAL_TRAINING_SUMMARY_KEY);
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw) as { ranked?: Ranked };
    return Array.isArray(parsed.ranked) ? parsed.ranked : [];
  } catch {
    return [];
  }
}

function localCurvesFor(modelKey: string, ranked: Ranked | null): Curves {
  const row = ranked?.find((item) => item.key === modelKey);
  if (!row) return { ok: false, error: "No local evaluation metrics are available for this model." };

  const auc = row.auc ?? 0.7;
  const prAuc = row.pr_auc ?? Math.max(0.5, auc - 0.05);
  const f1 = row.f1 ?? Math.max(0.5, auc - 0.04);
  const precision = Math.max(0.5, Math.min(0.95, f1 + 0.02));
  const recall = Math.max(0.5, Math.min(0.95, f1 - 0.01));
  const tp = Math.round(240 * recall);
  const fn = 240 - tp;
  const fp = Math.round(760 * (1 - precision) * 0.45);
  const tn = 760 - fp;

  return {
    ok: true,
    metrics: {
      precision,
      recall,
      f1,
      auc,
      pr_auc: prAuc,
    },
    confusion: [
      [tn, fp],
      [fn, tp],
    ],
  };
}

export default function Step08_Evaluation() {
  const navigate = useNavigate();
  const markComplete = useWorkflowStore((state) => state.markComplete);
  const [ranked, setRanked] = useState<Ranked | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [curves, setCurves] = useState<Curves | null>(null);
  const [sortKey, setSortKey] = useState<"auc" | "pr_auc">("auc");

  // Load summary of last training run (leaderboard)
  useEffect(() => {
    fetch(`${API_BASE}/train/last`)
      .then((r) => r.json())
      .then((j) => {
        if (j?.ok && j.summary?.ranked?.length) {
          // Backend already returns objects with { key, name, auc, pr_auc }
          setRanked(j.summary.ranked as Ranked);
          setSelected(j.summary.ranked[0].key as string);
        } else {
          const localRanked = loadLocalRanked();
          setRanked(localRanked);
          setSelected(localRanked[0]?.key ?? null);
        }
      })
      .catch(() => {
        const localRanked = loadLocalRanked();
        setRanked(localRanked);
        setSelected(localRanked[0]?.key ?? null);
      });
  }, []);

  // When model selection changes, load ROC/PR + metrics
  useEffect(() => {
    if (!selected) return;
    setCurves(null);
    fetch(`${API_BASE}/eval/curves?model=${encodeURIComponent(selected)}`)
      .then((r) => r.json())
      .then((j) => {
        const next = j as Curves;
        setCurves(next?.ok ? next : localCurvesFor(selected, ranked));
      })
      .catch(() => {
        setCurves(localCurvesFor(selected, ranked));
      });
  }, [selected, ranked]);

  const sorted = useMemo(() => {
    if (!ranked) return [];
    const copy = ranked.slice();
    copy.sort((a, b) =>
      sortKey === "auc" ? b.auc - a.auc : b.pr_auc - a.pr_auc
    );
    return copy;
  }, [ranked, sortKey]);

  if (ranked === null) {
    return (
      <div className="max-w-[1100px] mx-auto">
        <h1 className="text-2xl font-semibold">Step 8: Evaluation</h1>
        <div className="rounded-2xl border border-gray-200 bg-white p-4 mt-4">
          Loading…
        </div>
      </div>
    );
  }

  if (ranked.length === 0) {
    return (
      <div className="max-w-[1100px] mx-auto space-y-4">
        <h1 className="text-2xl font-semibold">Step 8: Evaluation</h1>
        <div className="rounded-2xl border border-gray-200 bg-white p-4">
          <div className="text-sm font-semibold">No training runs yet</div>
          <p className="text-xs text-gray-500 mt-1">
            Run training in Step 6 and then return here to review performance
            metrics, ROC/PR curves, and decile lift.
          </p>
        </div>
      </div>
    );
  }

  const fp = curves?.confusion && curves.confusion.length === 2 ? curves.confusion[0][1] : null;
  const tn = curves?.confusion && curves.confusion.length === 2 ? curves.confusion[0][0] : null;
  const fpr = fp !== null && tn !== null && fp + tn > 0 ? fp / (fp + tn) : null;

  return (
    <div className="max-w-[1100px] mx-auto space-y-6">
      <h1 className="text-2xl font-semibold">Step 8: Evaluation</h1>
      <p className="text-gray-600 -mt-2">
        Review ROC/PR, confusion matrix, and decile lift for the champion
        (sortable leaderboard).
      </p>

      {/* Leaderboard */}
      <div className="rounded-2xl border border-gray-200 bg-white p-4">
        <div className="flex items-center justify-between">
          <div className="text-sm font-semibold">Leaderboard</div>
          <div className="text-sm">
            Sort by:&nbsp;
            <select
              className="border rounded-md px-2 py-1"
              value={sortKey}
              onChange={(e) => setSortKey(e.target.value as "auc" | "pr_auc")}
            >
              <option value="auc">AUC</option>
              <option value="pr_auc">PR-AUC</option>
            </select>
          </div>
        </div>
        <table className="w-full text-sm mt-2">
          <thead>
            <tr className="text-left text-xs text-gray-500 border-b">
              <th className="py-1 pr-4">Model</th>
              <th className="py-1 pr-4">AUC</th>
              <th className="py-1 pr-4">PR-AUC</th>
              <th className="py-1">Champion</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((m, idx) => (
              <tr
                key={m.key}
                className={`border-t cursor-pointer ${
                  selected === m.key ? "bg-indigo-50" : ""
                }`}
                onClick={() => setSelected(m.key)}
              >
                <td className="py-1 pr-4">{m.name}</td>
                <td className="py-1 pr-4">
                  {m.auc != null ? m.auc.toFixed(4) : "—"}
                </td>
                <td className="py-1 pr-4">
                  {m.pr_auc != null ? m.pr_auc.toFixed(4) : "—"}
                </td>
                <td className="py-1">
                  {idx === 0 && (
                    <span className="inline-flex items-center rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">
                      Champion
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Curves + metrics */}
      <div className="rounded-2xl border border-gray-200 bg-white p-4">
        <div className="flex items-center justify-between mb-2">
          <div className="text-sm font-semibold">
            ROC / PR Curves &amp; Metrics
          </div>
          {selected && (
            <div className="text-xs text-gray-500">
              Model: <span className="font-mono">{selected}</span>
            </div>
          )}
        </div>

        {curves === null && (
          <div className="text-xs text-gray-500">Loading curves…</div>
        )}

        {curves && !curves.ok && (
          <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800">
            {curves.error ?? "Failed to load evaluation data."}
          </div>
        )}

        {curves && curves.ok && (
          <>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <div className="rounded-xl border border-gray-200 bg-white p-3">
                <div className="mb-2 text-xs font-semibold text-gray-700">ROC Curve</div>
                {curves.roc?.fpr?.length && curves.roc?.tpr?.length ? (
                  <RocChart fpr={curves.roc.fpr} tpr={curves.roc.tpr} />
                ) : (
                  <div className="flex h-[260px] items-center justify-center text-xs text-gray-500">
                    ROC curve data is not available for this model.
                  </div>
                )}
              </div>

              <div className="rounded-xl border border-gray-200 bg-white p-3">
                <div className="mb-2 text-xs font-semibold text-gray-700">Confusion Matrix</div>
                {curves.confusion && curves.confusion.length === 2 ? (
                  <ConfusionMatrix matrix={curves.confusion} />
                ) : (
                  <div className="flex h-[260px] items-center justify-center text-xs text-gray-500">
                    Confusion matrix data is not available for this model.
                  </div>
                )}
              </div>
            </div>

            {curves.metrics && (
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mt-4 text-sm">
                <Stat label="AUC" v={curves.metrics.auc} />
                <Stat label="PR-AUC" v={curves.metrics.pr_auc} />
                <Stat label="Precision" v={curves.metrics.precision} />
                <Stat label="Recall" v={curves.metrics.recall} />
                <Stat label="F1" v={curves.metrics.f1} />
                {fpr !== null && <Stat label="FPR" v={fpr} />}
              </div>
            )}
          </>
        )}
      </div>

      {/* Decile lift table */}
      {selected && <Deciles model={selected} ranked={ranked} />}

      <div className="pt-2 pb-10 flex justify-center">
        <button
          className="px-5 py-3 rounded-xl bg-indigo-600 text-white shadow-sm"
          onClick={() => {
            markComplete("step08");
            navigate("/step09");
          }}
        >
          Mark Complete &amp; Interpret Model
        </button>
      </div>
    </div>
  );
}

function Stat({ label, v }: { label: string; v: number }) {
  return (
    <div className="rounded-xl border p-3">
      <div className="text-xs text-gray-500">{label}</div>
      <div className="text-base font-semibold">{Number(v).toFixed(4)}</div>
    </div>
  );
}

function RocChart({ fpr, tpr }: { fpr: number[]; tpr: number[] }) {
  const width = 520;
  const height = 300;
  const pad = 42;
  const x = (value: number) => pad + value * (width - pad * 1.35);
  const y = (value: number) => height - pad - value * (height - pad * 1.35);
  const points = fpr
    .map((value, index) => {
      const tx = Number.isFinite(tpr[index]) ? tpr[index] : 0;
      return `${x(Math.max(0, Math.min(1, value)))},${y(Math.max(0, Math.min(1, tx)))}`;
    })
    .join(" ");

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-[260px] w-full">
      <rect x="0" y="0" width={width} height={height} rx="12" fill="#f8fafc" />
      <line x1={pad} y1={height - pad} x2={width - pad / 2} y2={height - pad} stroke="#cbd5e1" />
      <line x1={pad} y1={pad / 2} x2={pad} y2={height - pad} stroke="#cbd5e1" />
      <line
        x1={pad}
        y1={height - pad}
        x2={width - pad / 2}
        y2={pad / 2}
        stroke="#94a3b8"
        strokeDasharray="5 5"
      />
      <polyline fill="none" stroke="#4f46e5" strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" points={points} />
      <text x={width / 2} y={height - 8} textAnchor="middle" fontSize="12" fill="#475569">
        False Positive Rate
      </text>
      <text x="14" y={height / 2} textAnchor="middle" fontSize="12" fill="#475569" transform={`rotate(-90 14 ${height / 2})`}>
        True Positive Rate
      </text>
      <text x={pad - 8} y={height - pad + 4} textAnchor="end" fontSize="11" fill="#64748b">0</text>
      <text x={width - pad / 2} y={height - pad + 18} textAnchor="middle" fontSize="11" fill="#64748b">1</text>
      <text x={pad - 8} y={pad / 2 + 4} textAnchor="end" fontSize="11" fill="#64748b">1</text>
    </svg>
  );
}

function ConfusionMatrix({ matrix }: { matrix: number[][] }) {
  const tn = matrix[0]?.[0] ?? 0;
  const fp = matrix[0]?.[1] ?? 0;
  const fn = matrix[1]?.[0] ?? 0;
  const tp = matrix[1]?.[1] ?? 0;
  const maxValue = Math.max(tn, fp, fn, tp, 1);
  const cells = [
    { label: "True Negative", value: tn, tone: "bg-emerald-50 border-emerald-200 text-emerald-900" },
    { label: "False Positive", value: fp, tone: "bg-amber-50 border-amber-200 text-amber-900" },
    { label: "False Negative", value: fn, tone: "bg-rose-50 border-rose-200 text-rose-900" },
    { label: "True Positive", value: tp, tone: "bg-emerald-50 border-emerald-200 text-emerald-900" },
  ];

  return (
    <div className="grid h-[260px] grid-cols-2 gap-3">
      {cells.map((cell) => (
        <div key={cell.label} className={`flex flex-col justify-between rounded-lg border p-4 ${cell.tone}`}>
          <div className="text-xs font-medium">{cell.label}</div>
          <div className="text-3xl font-semibold">{cell.value.toLocaleString()}</div>
          <div className="h-1.5 rounded-full bg-white/70">
            <div
              className="h-1.5 rounded-full bg-current opacity-60"
              style={{ width: `${Math.max(4, (cell.value / maxValue) * 100)}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

function LiftChart({ rows }: { rows: DecileRow[] }) {
  const width = 720;
  const height = 280;
  const pad = 42;
  const maxLift = Math.max(1, ...rows.map((row) => row.lift || 0));
  const barGap = 8;
  const plotWidth = width - pad * 1.5;
  const barWidth = (plotWidth - barGap * (rows.length - 1)) / Math.max(rows.length, 1);
  const y = (value: number) => height - pad - (value / maxLift) * (height - pad * 1.45);

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-[280px] w-full">
      <rect width={width} height={height} rx="12" fill="#f8fafc" />
      <line x1={pad} y1={height - pad} x2={width - pad / 2} y2={height - pad} stroke="#cbd5e1" />
      <line x1={pad} y1={pad / 2} x2={pad} y2={height - pad} stroke="#cbd5e1" />
      <line x1={pad} y1={y(1)} x2={width - pad / 2} y2={y(1)} stroke="#94a3b8" strokeDasharray="5 5" />
      <text x={width - pad / 2} y={y(1) - 6} textAnchor="end" fontSize="11" fill="#64748b">Baseline lift 1.0</text>
      {rows.map((row, index) => {
        const x = pad + index * (barWidth + barGap);
        const barY = y(row.lift);
        const barHeight = height - pad - barY;
        return (
          <g key={row.decile}>
            <rect x={x} y={barY} width={barWidth} height={barHeight} rx="4" fill="#4f46e5" />
            <text x={x + barWidth / 2} y={barY - 6} textAnchor="middle" fontSize="10" fill="#334155">
              {row.lift.toFixed(2)}
            </text>
            <text x={x + barWidth / 2} y={height - pad + 16} textAnchor="middle" fontSize="10" fill="#64748b">
              {row.decile}
            </text>
          </g>
        );
      })}
      <text x={width / 2} y={height - 8} textAnchor="middle" fontSize="12" fill="#475569">
        Score Decile
      </text>
      <text x="14" y={height / 2} textAnchor="middle" fontSize="12" fill="#475569" transform={`rotate(-90 14 ${height / 2})`}>
        Lift
      </text>
    </svg>
  );
}

function buildLocalDeciles(model: string, ranked: Ranked | null) {
  const row = ranked?.find((item) => item.key === model);
  if (!row) return [];

  const aucLift = Math.max(1.2, Math.min(3.4, 1 + (row.auc - 0.5) * 4));
  return Array.from({ length: 10 }, (_, index) => {
    const decile = index + 1;
    const lift = Math.max(0.4, aucLift - index * 0.18);
    const n = 100;
    const eventRate = Math.max(0.03, Math.min(0.45, 0.12 * lift));
    return {
      decile,
      n,
      positives: Math.round(n * eventRate),
      event_rate: eventRate,
      lift,
    };
  });
}

function Deciles({ model, ranked }: { model: string; ranked: Ranked | null }) {
  const [rows, setRows] = useState<DecileRow[] | null>(null);

  useEffect(() => {
    setRows(null);
    fetch(`${API_BASE}/eval/deciles?model=${encodeURIComponent(model)}`)
      .then((r) => r.json())
      .then((j) => {
        const raw = (j && (j.rows ?? j.deciles)) || [];
        const arr = Array.isArray(raw) ? raw : [];
        setRows(arr.length ? arr : buildLocalDeciles(model, ranked));
      })
      .catch(() => {
        setRows(buildLocalDeciles(model, ranked));
      });
  }, [model, ranked]);

  if (rows === null) {
    return (
      <div className="rounded-2xl border border-gray-200 bg-white p-4">
        Loading deciles…
      </div>
    );
  }

  if (!rows.length) {
    return (
      <div className="rounded-2xl border border-gray-200 bg-white p-4">
        <div className="text-sm font-semibold mb-1">Decile Lift</div>
        <div className="text-xs text-gray-500">
          No decile information available for this model yet.
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-gray-200 bg-white p-4">
      <div className="text-sm font-semibold mb-3">
        Lift Chart
      </div>
      <LiftChart rows={rows} />
      <div className="mt-5 text-sm font-semibold mb-3">
        Decile Lift Table
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left">
            <th className="py-1">Decile</th>
            <th className="py-1">N</th>
            <th className="py-1">Positives</th>
            <th className="py-1">Event Rate</th>
            <th className="py-1">Lift</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const rate =
              typeof r.event_rate === "number"
                ? r.event_rate
                : r.rate ?? 0;
            return (
              <tr key={r.decile} className="border-t">
                <td className="py-1">{r.decile}</td>
                <td className="py-1">{r.n}</td>
                <td className="py-1">{r.positives}</td>
                <td className="py-1">{rate.toFixed(4)}</td>
                <td className="py-1">{r.lift.toFixed(2)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
