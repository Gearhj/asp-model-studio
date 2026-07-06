import { useEffect, useMemo, useState } from "react";
import StepShell from "../components/StepShell";
import { logDecision } from "../lib/decisionJournal";
import { inferLocalProblemType, loadLocalDataset } from "../lib/localDataset";
import { useWorkflowStore } from "../state/useWorkflowStore";

const API_BASE =
  import.meta.env.VITE_API_BASE?.replace(/\/$/, "") || "http://127.0.0.1:8001/api";

type SplitStrategy = "holdout" | "kfold";
type BalanceMethod = "undersample" | "smote" | "class_weight" | "none";

const RATIO_OPTIONS = ["90/10", "80/20", "70/30", "60/40"];
const KFOLD_OPTIONS = [3, 4, 5, 6, 7, 8, 9, 10];
const splitGuidance: Record<SplitStrategy, string> = {
  holdout: "Definition: one train/test split. Use when you need a simple independent test set or will score separate TEST/OOT files later.",
  kfold: "Definition: repeated train/validation folds with preserved class mix. Use when the development sample is small or model selection needs more stable estimates.",
};
const balanceGuidance: Record<BalanceMethod, string> = {
  undersample: "Definition: reduce majority-class records in training. Use for rare-event classification when fast training and lift/recall matter.",
  smote: "Definition: synthesize minority-class examples in training. Use cautiously when the minority class has enough structure and synthetic cases are defensible.",
  class_weight: "Definition: penalize minority-class errors more heavily. Use when you want to preserve all records while addressing imbalance.",
  none: "Definition: do not alter class distribution. Use when event rate is acceptable or balancing would distort the production population.",
};

// Color convention: blue = Non-Fraud (0), red = Fraud (1)
const BLUE = "bg-blue-500";
const RED = "bg-red-500";

function parseRatio(r: string): { maj: number; min: number } {
  const [a, b] = r.split("/").map((x) => parseInt(x, 10));
  const maj = Number.isFinite(a) ? a : 80;
  const min = Number.isFinite(b) ? b : 20;
  return { maj, min };
}

function numericArray(rows: Record<string, any>[], column: string) {
  return rows.map((row) => Number(row[column])).filter(Number.isFinite);
}

function summarizeValues(values: number[]) {
  const sorted = [...values].sort((a, b) => a - b);
  const q = (p: number) => {
    if (!sorted.length) return 0;
    const index = (sorted.length - 1) * p;
    const lo = Math.floor(index);
    const hi = Math.ceil(index);
    const weight = index - lo;
    return sorted[lo] * (1 - weight) + sorted[hi] * weight;
  };
  const mean = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
  const variance = values.length > 1 ? values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / (values.length - 1) : 0;
  return {
    n: values.length,
    mean,
    median: q(0.5),
    std: Math.sqrt(variance),
    min: sorted[0] ?? 0,
    max: sorted[sorted.length - 1] ?? 0,
  };
}

function niceTicks(min: number, max: number, count = 5) {
  if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) return [min || 0];
  return Array.from({ length: count }, (_, index) => min + ((max - min) * index) / (count - 1));
}

/**
 * Full-width two-color bar (blue+red) that always sums to 100%.
 * No gray background fill; only a thin border so colors fill the track.
 */
function StackBar({
  majPct,
  minPct,
  height = 10,
  title,
}: {
  majPct: number;
  minPct: number;
  height?: number;
  title?: string;
}) {
  // Normalize defensively so segments always fill the bar
  const m = Math.max(0, Math.min(100, majPct));
  const n = Math.max(0, Math.min(100, minPct));
  const total = m + n || 1;
  const blueW = (m / total) * 100;
  const redW = 100 - blueW;

  return (
    <div
      className="w-full rounded overflow-hidden border border-gray-300"
      style={{ height }}
      title={title}
    >
      <div className="h-full w-full flex">
        <div className={`h-full ${BLUE}`} style={{ width: `${blueW}%` }} />
        <div className={`h-full ${RED}`} style={{ width: `${redW}%` }} />
      </div>
    </div>
  );
}

function Block({
  label,
  kind, // "train" | "validation"
  majPct,
  minPct,
  caption,
}: {
  label: string;
  kind: "train" | "validation";
  majPct: number;
  minPct: number;
  caption: string;
}) {
  const frame =
    kind === "validation"
      ? "bg-amber-50 border-amber-200"
      : "bg-blue-50 border-blue-200";
  return (
    <div className={`rounded border p-2 flex flex-col gap-1 ${frame}`}>
      <div className="text-[11px] font-semibold text-gray-800">{label}</div>
      <StackBar majPct={majPct} minPct={minPct} />
      <div className="text-[10px] text-gray-600">{caption}</div>
      <div className="text-[10px] text-gray-700">
        Non-Fraud <span className="font-semibold">{majPct}%</span> | Fraud{" "}
        <span className="font-semibold">{minPct}%</span>
      </div>
    </div>
  );
}

function KFoldRow({
  rowIndex,
  k,
  balanceMethod,
  trainMaj,
  trainMin,
  valMaj,
  valMin,
}: {
  rowIndex: number; // 0..k-1
  k: number;
  balanceMethod: BalanceMethod;
  trainMaj: number;
  trainMin: number;
  valMaj: number;
  valMin: number;
}) {
  return (
    <div className="flex items-center gap-3">
      <div className="w-28 text-xs text-gray-700 font-medium shrink-0">{`Iteration ${String(
        rowIndex + 1
      ).padStart(2, "0")}`}</div>

      <div
        className="flex-1 grid"
        style={{ gridTemplateColumns: `repeat(${k}, minmax(0, 1fr))`, gap: "8px" }}
      >
        {Array.from({ length: k }).map((_, j) => {
          const isVal = j === rowIndex;
          if (isVal) {
            return (
              <Block
                key={j}
                label="Validation"
                kind="validation"
                majPct={valMaj}
                minPct={valMin}
                caption="original prevalence (preview)"
              />
            );
          }
          const cap =
            balanceMethod === "undersample"
              ? "train target (undersampling)"
              : balanceMethod === "smote"
              ? "balanced by SMOTE (preview)"
              : balanceMethod === "class_weight"
              ? "balanced by class weights (preview)"
              : "no balancing (preview)";
          return (
            <Block
              key={j}
              label="Train"
              kind="train"
              majPct={trainMaj}
              minPct={trainMin}
              caption={cap}
            />
          );
        })}
      </div>
    </div>
  );
}

function KFoldPreview({
  k,
  balanceMethod,
  undersampleRatio,
  valPreviewRatio,
}: {
  k: number;
  balanceMethod: BalanceMethod;
  undersampleRatio: string;
  valPreviewRatio: string;
}) {
  const us = parseRatio(undersampleRatio);
  const val = parseRatio(valPreviewRatio);

  // In non-undersampling modes, show preview using validation prevalence;
  // caption clarifies the exact balancing is method-driven.
  const trainMaj = balanceMethod === "undersample" ? us.maj : val.maj;
  const trainMin = balanceMethod === "undersample" ? us.min : val.min;

  return (
    <div className="mt-4 space-y-2">
      {Array.from({ length: k }).map((_, i) => (
        <KFoldRow
          key={i}
          rowIndex={i}
          k={k}
          balanceMethod={balanceMethod}
          trainMaj={trainMaj}
          trainMin={trainMin}
          valMaj={val.maj}
          valMin={val.min}
        />
      ))}

      <div className="flex items-center gap-4 text-[11px] text-gray-600 mt-2">
        <div className="flex items-center gap-2">
          <div className="w-4 h-3 rounded bg-blue-200 border border-blue-300" />
          <span>Train fold</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-4 h-3 rounded bg-amber-200 border border-amber-300" />
          <span>Validation fold</span>
        </div>
        <div className="ml-2">
          Bars show class mix: <span className="text-blue-600 font-medium">Non-Fraud</span> vs{" "}
          <span className="text-red-600 font-medium">Fraud</span>.
        </div>
      </div>
      <p className="text-[11px] text-gray-500">
        <b>Note:</b> In cross-validation, balancing is applied to <b>training folds only</b>;
        validation folds remain untouched. Visual ratios here are previews (no data leakage).
      </p>
    </div>
  );
}

function TargetSummaryCard({
  title,
  rows,
  summary,
}: {
  title: string;
  rows: number;
  summary: ReturnType<typeof summarizeValues>;
}) {
  const stats = [
    ["Rows", rows.toLocaleString()],
    ["Mean", summary.mean.toFixed(4)],
    ["Median", summary.median.toFixed(4)],
    ["Std Dev", summary.std.toFixed(4)],
    ["Min", summary.min.toFixed(4)],
    ["Max", summary.max.toFixed(4)],
  ];
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
      <div className="text-sm font-semibold text-slate-900">{title}</div>
      <div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-3">
        {stats.map(([label, value]) => (
          <div key={label} className="rounded-lg border border-slate-100 bg-white p-2">
            <div className="text-[10px] font-semibold uppercase text-slate-500">{label}</div>
            <div className="mt-1 text-sm font-semibold text-slate-900">{value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function SplitDistributionChart({ train, holdout }: { train: number[]; holdout: number[] }) {
  const width = 760;
  const height = 300;
  const pad = 52;
  const all = [...train, ...holdout].filter(Number.isFinite);
  if (!all.length) return <div className="flex h-[220px] items-center justify-center text-sm text-slate-500">No numeric target values available.</div>;
  const min = Math.min(...all);
  const max = Math.max(...all);
  const bins = 28;
  const countsFor = (values: number[]) => {
    const counts = new Array(bins).fill(0);
    values.forEach((value) => {
      const index = Math.max(0, Math.min(bins - 1, Math.floor(((value - min) / (max - min || 1)) * bins)));
      counts[index] += 1;
    });
    return counts;
  };
  const trainCounts = countsFor(train);
  const holdoutCounts = countsFor(holdout);
  const maxCount = Math.max(1, ...trainCounts, ...holdoutCounts);
  const plotWidth = width - pad * 1.4;
  const plotHeight = height - pad * 1.5;
  const barWidth = plotWidth / bins;
  const y = (value: number) => height - pad - (value / maxCount) * plotHeight;
  const x = (value: number) => pad + ((value - min) / (max - min || 1)) * plotWidth;
  const trainMean = train.reduce((sum, value) => sum + value, 0) / Math.max(train.length, 1);
  const holdoutMean = holdout.reduce((sum, value) => sum + value, 0) / Math.max(holdout.length, 1);
  const xTicks = niceTicks(min, max, 6);
  const yTicks = niceTicks(0, maxCount, 5);
  return (
    <div>
    <svg viewBox={`0 0 ${width} ${height}`} className="h-[300px] w-full rounded-xl bg-white">
      {yTicks.map((tick) => (
        <g key={`y-${tick}`}>
          <line x1={pad} y1={y(tick)} x2={width - pad / 2} y2={y(tick)} stroke="#e2e8f0" />
          <text x={pad - 8} y={y(tick) + 4} textAnchor="end" className="fill-slate-500 text-[10px]">{Math.round(tick)}</text>
        </g>
      ))}
      <line x1={pad} y1={height - pad} x2={width - pad / 2} y2={height - pad} stroke="#cbd5e1" />
      <line x1={pad} y1={pad / 2} x2={pad} y2={height - pad} stroke="#cbd5e1" />
      {trainCounts.map((count, index) => {
        const x = pad + index * barWidth;
        const barY = y(count);
        return <rect key={`t-${index}`} x={x + 1} y={barY} width={Math.max(1, barWidth / 2 - 1)} height={height - pad - barY} rx={2} fill="#4f46e5" opacity={0.75} />;
      })}
      {holdoutCounts.map((count, index) => {
        const x = pad + index * barWidth + barWidth / 2;
        const barY = y(count);
        return <rect key={`h-${index}`} x={x + 1} y={barY} width={Math.max(1, barWidth / 2 - 1)} height={height - pad - barY} rx={2} fill="#0f766e" opacity={0.75} />;
      })}
      <line x1={x(trainMean)} x2={x(trainMean)} y1={pad / 2} y2={height - pad} stroke="#4f46e5" strokeWidth={2} strokeDasharray="5 4" />
      <line x1={x(holdoutMean)} x2={x(holdoutMean)} y1={pad / 2} y2={height - pad} stroke="#0f766e" strokeWidth={2} strokeDasharray="5 4" />
      {xTicks.map((tick) => (
        <g key={`x-${tick}`}>
          <line x1={x(tick)} x2={x(tick)} y1={height - pad} y2={height - pad + 5} stroke="#94a3b8" />
          <text x={x(tick)} y={height - pad + 18} textAnchor="middle" className="fill-slate-500 text-[10px]">{tick.toFixed(2)}</text>
        </g>
      ))}
      <text x={pad} y={22} className="fill-indigo-700 text-[11px]">Train</text>
      <text x={pad + 58} y={22} className="fill-teal-700 text-[11px]">Holdout</text>
      <text x={pad + 128} y={22} className="fill-slate-500 text-[11px]">Dashed lines = means</text>
      <text x={width / 2} y={height - 8} textAnchor="middle" className="fill-slate-600 text-[11px]">Target value</text>
      <text x={14} y={height / 2} textAnchor="middle" transform={`rotate(-90 14 ${height / 2})`} className="fill-slate-600 text-[11px]">Records</text>
    </svg>
    <div className="mt-2 rounded-lg border border-slate-200 bg-white p-3 text-xs leading-5 text-slate-600">
      <span className="font-semibold text-slate-800">ATLAS readout: </span>
      Train mean {trainMean.toFixed(4)} vs holdout mean {holdoutMean.toFixed(4)}. Comparable distributions reduce validation bias; material shifts should be reviewed before model training.
    </div>
    </div>
  );
}

export default function Step06_BalancingSplit() {
  const { markCompleteAndNext, getNextStepPath } = useWorkflowStore();
  const dataset = loadLocalDataset();
  const problemType = inferLocalProblemType(dataset) ?? dataset?.problem_type ?? "classification";
  const isRegression = problemType === "regression";

  // Path for the next step (Model Training) based on the workflow store
  const nextPath = getNextStepPath("step06");

  // Mark this step complete and persist split/balancing config to the backend
  const handleNext = async () => {
    const payload = {
      split_strategy: splitStrategy,
      k_folds: kFolds,
      balance_method: balanceMethod,
      balance_ratio: balanceRatio,
    };

    try {
      const res = await fetch(`${API_BASE}/balancing_split/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        console.error("Failed to persist split config:", await res.text());
      }
    } catch (err) {
      console.error("Failed to persist split config:", err);
    }

    markCompleteAndNext("step06");
  };


  const [splitStrategy, setSplitStrategy] = useState<SplitStrategy>(() => {
    return (localStorage.getItem("splitStrategy") as SplitStrategy) || "holdout";
  });
  const [kFolds, setKFolds] = useState<number>(() => {
    const v = Number(localStorage.getItem("kFolds") || "5");
    return Number.isFinite(v) ? Math.min(10, Math.max(3, v)) : 5;
  });

  const [balanceRatio, setBalanceRatio] = useState<string>(() => {
    return localStorage.getItem("balanceRatio") || "80/20";
  });
  const [balanceMethod, setBalanceMethod] = useState<BalanceMethod>(() => {
    return (localStorage.getItem("balanceMethod") as BalanceMethod) || "undersample";
  });

  // persist
  useEffect(() => {
    localStorage.setItem("splitStrategy", splitStrategy);
  }, [splitStrategy]);
  useEffect(() => {
    localStorage.setItem("kFolds", String(kFolds));
  }, [kFolds]);
  useEffect(() => {
    localStorage.setItem("balanceRatio", balanceRatio);
  }, [balanceRatio]);
  useEffect(() => {
    localStorage.setItem("balanceMethod", balanceMethod);
  }, [balanceMethod]);

  const chooseSplitStrategy = (next: SplitStrategy) => {
    logDecision({
      workflowStep: "Balance & Split",
      actionType: "split_strategy_selected",
      subject: "Split strategy",
      previousValue: splitStrategy,
      newValue: next,
    });
    setSplitStrategy(next);
  };

  const chooseBalanceMethod = (next: BalanceMethod) => {
    logDecision({
      workflowStep: "Balance & Split",
      actionType: "balancing_method_selected",
      subject: "Balancing method",
      previousValue: balanceMethod,
      newValue: next,
    });
    setBalanceMethod(next);
  };

  const chooseBalanceRatio = (next: string) => {
    logDecision({
      workflowStep: "Balance & Split",
      actionType: "workflow_setting_changed",
      subject: "Balance / holdout ratio",
      previousValue: balanceRatio,
      newValue: next,
    });
    setBalanceRatio(next);
  };

  const { maj, min } = useMemo(() => parseRatio(balanceRatio), [balanceRatio]);
  const regressionSplit = useMemo(() => {
    const rows = dataset?.rows ?? [];
    const target = dataset?.target ?? "";
    const nums = numericArray(rows, target);
    const mean = nums.length ? nums.reduce((sum, value) => sum + value, 0) / nums.length : null;
    const { maj: devPct, min: holdoutPct } = parseRatio(balanceRatio);
    const developmentRows = Math.round(rows.length * (devPct / 100));
    const holdoutRows = Math.max(0, rows.length - developmentRows);
    const trainRows = rows.slice(0, developmentRows);
    const holdout = rows.slice(developmentRows);
    const trainTarget = numericArray(trainRows, target);
    const holdoutTarget = numericArray(holdout, target);
    const featureAlignment = (dataset?.headers ?? [])
      .filter((header) => header !== target)
      .filter((header) => rows.slice(0, 250).some((row) => Number.isFinite(Number(row[header]))))
      .slice(0, 8)
      .map((feature) => {
        const trainMean = summarizeValues(numericArray(trainRows, feature)).mean;
        const holdoutMean = summarizeValues(numericArray(holdout, feature)).mean;
        const diff = holdoutMean - trainMean;
        const pctDiff = trainMean ? (diff / Math.abs(trainMean)) * 100 : 0;
        return {
          feature,
          trainMean,
          holdoutMean,
          diff,
          pctDiff,
          warning: Math.abs(pctDiff) > 10 ? "Review" : "Pass",
        };
      });
    const maxPctDiff = Math.max(0, ...featureAlignment.map((row) => Math.abs(row.pctDiff)));
    return {
      rows: rows.length,
      mean,
      developmentRows,
      holdoutRows,
      devPct,
      holdoutPct,
      trainRows,
      holdout,
      trainSummary: summarizeValues(trainTarget),
      holdoutSummary: summarizeValues(holdoutTarget),
      featureAlignment,
      splitQuality: maxPctDiff > 20 ? "Needs Review" : maxPctDiff > 10 ? "Watch" : "Aligned",
    };
  }, [dataset, balanceRatio]);

  const isHoldout = splitStrategy === "holdout";
  const isCV = splitStrategy === "kfold";

  if (isRegression) {
    return (
      <StepShell
        title="Step 6: Regression Split Validation"
        subtitle="Choose a validation design for a continuous target. Balancing, SMOTE, class weights, and event-rate controls are not applicable."
        onNext={handleNext}
        nextPath={nextPath}
      >
        <div className="space-y-6">
          <section className="rounded-xl border border-blue-200 bg-blue-50 p-5 text-sm text-blue-950">
            <div className="font-semibold">Regression workflow detected</div>
            <p className="mt-1">
              ATLAS will preserve the continuous target distribution and validate model fit using RMSE, MAE, MAPE, R-squared,
              adjusted R-squared, residual diagnostics, prediction PSI, and VSI. Class balancing controls are hidden because they
              only apply to classification.
            </p>
          </section>

          <section className="rounded-xl border border-gray-200 bg-white p-6">
            <h3 className="text-lg font-semibold text-gray-900">Validation Strategy</h3>
            <p className="mt-1 text-sm text-gray-600">Select how development data should be separated for model evaluation.</p>
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-slate-200 p-4">
                <input id="holdout" type="radio" checked={isHoldout} onChange={() => chooseSplitStrategy("holdout")} />
                <span>
                  <span className="text-sm font-semibold">Development Train / Holdout Validation</span>
                  <span className="mt-1 block text-xs leading-5 text-slate-500">
                    Definition: reserve one independent holdout sample. Use when external validation and OOT scoring will be performed later.
                  </span>
                </span>
              </label>
              <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-slate-200 p-4">
                <input id="kfold" type="radio" checked={isCV} onChange={() => chooseSplitStrategy("kfold")} />
                <span>
                  <span className="text-sm font-semibold">Regression K-Fold Cross-Validation</span>
                  <span className="mt-1 block text-xs leading-5 text-slate-500">
                    Definition: rotate validation folds and average regression error. Use when the sample is limited or model selection needs stable RMSE/MAE estimates.
                  </span>
                </span>
              </label>
            </div>

            {isCV ? (
              <div className="mt-5">
                <label className="block text-sm font-medium text-gray-700 mb-1">Number of folds (K)</label>
                <select
                  value={kFolds}
                  onChange={(e) => setKFolds(parseInt(e.target.value, 10))}
                  className="w-40 rounded-lg border border-gray-300 p-2"
                >
                  {KFOLD_OPTIONS.map((k) => <option key={k} value={k}>{k}</option>)}
                </select>
              </div>
            ) : (
              <div className="mt-5">
                <label className="block text-sm font-medium text-gray-700 mb-1">Holdout Validation Ratio</label>
                <select value={balanceRatio} onChange={(e) => chooseBalanceRatio(e.target.value)} className="w-full rounded-lg border border-gray-300 p-2">
                  {RATIO_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              </div>
            )}
          </section>

          <section className="rounded-xl border border-gray-200 bg-white p-6">
            <h3 className="text-lg font-semibold text-gray-900">Split Alignment Diagnostics</h3>
            <div className="mt-4 grid gap-3 md:grid-cols-4">
              <div className="rounded-xl border border-slate-100 bg-slate-50 p-4">
                <div className="text-xs font-semibold uppercase text-slate-500">Development Train</div>
                <div className="mt-1 text-2xl font-bold text-indigo-700">{isCV ? `${kFolds}-fold` : `${regressionSplit.devPct}%`}</div>
                <p className="mt-1 text-xs text-slate-500">{isCV ? "Rotating folds" : `${regressionSplit.developmentRows.toLocaleString()} rows`}</p>
              </div>
              <div className="rounded-xl border border-slate-100 bg-slate-50 p-4">
                <div className="text-xs font-semibold uppercase text-slate-500">Holdout Validation</div>
                <div className="mt-1 text-2xl font-bold text-purple-700">{isCV ? "OOF" : `${regressionSplit.holdoutPct}%`}</div>
                <p className="mt-1 text-xs text-slate-500">{isCV ? "Out-of-fold predictions" : `${regressionSplit.holdoutRows.toLocaleString()} rows`}</p>
              </div>
              <div className="rounded-xl border border-slate-100 bg-slate-50 p-4">
                <div className="text-xs font-semibold uppercase text-slate-500">Target Mean</div>
                <div className="mt-1 text-2xl font-bold text-slate-900">{regressionSplit.mean === null ? "-" : regressionSplit.mean.toFixed(4)}</div>
                <p className="mt-1 text-xs text-slate-500">Continuous target baseline</p>
              </div>
              <div className="rounded-xl border border-emerald-100 bg-emerald-50 p-4">
                <div className="text-xs font-semibold uppercase text-emerald-700">Recommended Metrics</div>
                <div className="mt-1 text-sm font-semibold text-emerald-950">RMSE, MAE, R-squared</div>
                <p className="mt-1 text-xs text-emerald-700">Plus residual bias, prediction PSI, and VSI.</p>
              </div>
            </div>
          </section>

          {!isCV && (
            <section className="rounded-xl border border-gray-200 bg-white p-6">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className="text-lg font-semibold text-gray-900">Train vs Holdout Alignment</h3>
                  <p className="mt-1 text-sm text-slate-600">
                    ATLAS compares the continuous target and key predictors across the split so regression validation is not distorted by sample drift.
                  </p>
                </div>
                <span className={`rounded-full px-3 py-1 text-xs font-semibold ${
                  regressionSplit.splitQuality === "Aligned"
                    ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                    : regressionSplit.splitQuality === "Watch"
                    ? "bg-amber-50 text-amber-700 border border-amber-200"
                    : "bg-rose-50 text-rose-700 border border-rose-200"
                }`}>
                  Split quality: {regressionSplit.splitQuality}
                </span>
              </div>
              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                <TargetSummaryCard title="Development Train" rows={regressionSplit.developmentRows} summary={regressionSplit.trainSummary} />
                <TargetSummaryCard title="Holdout Validation" rows={regressionSplit.holdoutRows} summary={regressionSplit.holdoutSummary} />
              </div>
              <div className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4">
                <div className="mb-2 text-sm font-semibold text-slate-800">Target Distribution Comparison</div>
                <SplitDistributionChart train={numericArray(regressionSplit.trainRows, dataset?.target ?? "")} holdout={numericArray(regressionSplit.holdout, dataset?.target ?? "")} />
              </div>
              <div className="mt-5 overflow-hidden rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                    <tr>
                      <th className="px-3 py-2">Feature</th>
                      <th className="px-3 py-2">Train Mean</th>
                      <th className="px-3 py-2">Holdout Mean</th>
                      <th className="px-3 py-2">Diff</th>
                      <th className="px-3 py-2">% Diff</th>
                      <th className="px-3 py-2">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {regressionSplit.featureAlignment.map((row) => (
                      <tr key={row.feature} className="border-t">
                        <td className="px-3 py-2 font-medium">{row.feature}</td>
                        <td className="px-3 py-2">{row.trainMean.toFixed(4)}</td>
                        <td className="px-3 py-2">{row.holdoutMean.toFixed(4)}</td>
                        <td className="px-3 py-2">{row.diff.toFixed(4)}</td>
                        <td className="px-3 py-2">{row.pctDiff.toFixed(2)}%</td>
                        <td className={`px-3 py-2 font-semibold ${row.warning === "Pass" ? "text-emerald-700" : "text-amber-700"}`}>{row.warning}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </div>
      </StepShell>
    );
  }

  return (
    <StepShell
      title="Step 6: Data Balancing & Train/Test Split"
      subtitle="Balance class distribution and choose your split strategy"
      onNext={handleNext}
      nextPath={nextPath}
    >
      {/* Split strategy */}
      <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
        <div className="mb-4">
          <h3 className="text-lg font-semibold text-gray-900">Split Strategy</h3>
          <p className="text-sm text-gray-600">
            Choose between a traditional holdout split or Stratified K-Fold cross-validation.
          </p>
        </div>

        <div className="grid md:grid-cols-2 gap-4">
          <label className="flex items-center gap-3 cursor-pointer">
            <input
              id="holdout"
              type="radio"
              checked={isHoldout}
              onChange={() => chooseSplitStrategy("holdout")}
            />
            <span>
              <span className="text-sm font-medium">Holdout (Train/Test)</span>
              <span className="block text-[11px] leading-4 text-gray-500">{splitGuidance.holdout}</span>
            </span>
          </label>

          <label className="flex items-center gap-3 cursor-pointer">
            <input
              id="kfold"
              type="radio"
              checked={isCV}
              onChange={() => chooseSplitStrategy("kfold")}
            />
            <span>
              <span className="text-sm font-medium">Cross-validation (Stratified K-Fold)</span>
              <span className="block text-[11px] leading-4 text-gray-500">{splitGuidance.kfold}</span>
            </span>
          </label>
        </div>

        {/* K selector */}
        {isCV && (
          <div className="mt-4">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Number of folds (K)
            </label>
            <select
              value={kFolds}
              onChange={(e) => {
                const next = parseInt(e.target.value, 10);
                logDecision({
                  workflowStep: "Balance & Split",
                  actionType: "workflow_setting_changed",
                  subject: "K folds",
                  previousValue: kFolds,
                  newValue: next,
                });
                setKFolds(next);
              }}
              className="w-40 p-2 border border-gray-300 rounded-lg"
              title="Definition: number of resampling folds. Use 5 as a practical default; higher K can be slower but may reduce validation variance."
            >
              {KFOLD_OPTIONS.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
            <p className="mt-2 text-xs text-gray-600">
              In cross-validation, we train on K−1 folds and validate on the remaining fold. We
              repeat for each fold and aggregate out-of-fold (OOF) predictions.
            </p>

            {/* K-fold visualization */}
            <KFoldPreview
              k={kFolds}
              balanceMethod={balanceMethod}
              undersampleRatio={balanceRatio}
              valPreviewRatio={balanceRatio}
            />
          </div>
        )}
      </div>

      {/* Balancing */}
      <div className="rounded-xl border p-6 mb-6 bg-white">
        <div className="flex items-start justify-between">
          <h3 className="text-lg font-semibold text-gray-900">Balancing</h3>
          {isCV ? (
            <span className="text-xs text-gray-600">
              <b>CV mode:</b> balancing is applied to <b>training folds only</b>; validation folds
              remain untouched.
            </span>
          ) : (
            <span className="text-xs text-gray-600">
              Holdout mode: balancing is applied only to the <b>training</b> split.
            </span>
          )}
        </div>

        <div className="grid md:grid-cols-3 gap-6 mt-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Balance Ratio</label>
            <select
              value={balanceRatio}
              onChange={(e) => chooseBalanceRatio(e.target.value)}
              className="w-full p-2 border border-gray-300 rounded-lg"
              disabled={balanceMethod !== "undersample"}
              title={balanceMethod !== "undersample" ? "Ratio applies to undersampling only" : ""}
            >
              {RATIO_OPTIONS.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
            <p className="text-xs text-gray-500 mt-1">Definition: target majority/minority ratio after undersampling. Use 80/20 or 70/30 when rare events need stronger signal without fully balancing away population structure.</p>
          </div>

          <div className="col-span-2">
            <label className="block text-sm font-medium text-gray-700 mb-1">Method</label>
            <div className="flex flex-col gap-2">
              <label className="inline-flex items-center gap-2">
                <input
                  type="radio"
                  checked={balanceMethod === "undersample"}
                  onChange={() => chooseBalanceMethod("undersample")}
                />
                <span>
                  <span>Undersampling</span>
                  <span className="block text-[11px] leading-4 text-gray-500">{balanceGuidance.undersample}</span>
                </span>
              </label>
              <label className="inline-flex items-center gap-2">
                <input
                  type="radio"
                  checked={balanceMethod === "smote"}
                  onChange={() => chooseBalanceMethod("smote")}
                />
                <span>
                  <span>SMOTE (if available)</span>
                  <span className="block text-[11px] leading-4 text-gray-500">{balanceGuidance.smote}</span>
                </span>
              </label>
              <label className="inline-flex items-center gap-2">
                <input
                  type="radio"
                  checked={balanceMethod === "class_weight"}
                  onChange={() => chooseBalanceMethod("class_weight")}
                />
                <span>
                  <span>Class Weights</span>
                  <span className="block text-[11px] leading-4 text-gray-500">{balanceGuidance.class_weight}</span>
                </span>
              </label>
              <label className="inline-flex items-center gap-2">
                <input
                  type="radio"
                  checked={balanceMethod === "none"}
                  onChange={() => chooseBalanceMethod("none")}
                />
                <span>
                  <span>None</span>
                  <span className="block text-[11px] leading-4 text-gray-500">{balanceGuidance.none}</span>
                </span>
              </label>
            </div>
          </div>
        </div>

        {/* Combined distribution preview (full width, blue+red only) */}
        <div className="mt-6">
          <h4 className="text-sm font-semibold text-gray-700 mb-2">Distribution (preview)</h4>
          <StackBar majPct={maj} minPct={min} height={12} />
          <div className="mt-1 text-xs text-gray-700">
            Non-Fraud <span className="font-semibold">{maj}%</span> | Fraud{" "}
            <span className="font-semibold">{min}%</span>
          </div>
        </div>
      </div>

      {/* Optional simple holdout visual */}
      {isHoldout && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Train/Test Split</h3>
          <label className="block text-sm font-medium text-gray-700 mb-1">Holdout Ratio</label>
          <select
            value={balanceRatio}
            onChange={(e) => chooseBalanceRatio(e.target.value)}
            className="w-full p-2 border border-gray-300 rounded-lg"
          >
            {RATIO_OPTIONS.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
          <div className="grid grid-cols-2 gap-6 mt-4">
            <div className="rounded-xl bg-indigo-50 p-6 border border-indigo-100">
              <div className="text-sm text-indigo-700">Train</div>
              <div className="text-3xl font-bold text-indigo-700">{maj}%</div>
            </div>
            <div className="rounded-xl bg-purple-50 p-6 border border-purple-100">
              <div className="text-sm text-purple-700">Test</div>
              <div className="text-3xl font-bold text-purple-700">{min}%</div>
            </div>
          </div>
        </div>
      )}
    </StepShell>
  );
}
