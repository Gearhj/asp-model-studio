import { useEffect, useMemo, useState } from "react";
import StepShell from "../components/StepShell";
import { useWorkflowStore } from "../state/useWorkflowStore";

const API_BASE =
  import.meta.env.VITE_API_BASE?.replace(/\/$/, "") || "http://127.0.0.1:8001/api";

type SplitStrategy = "holdout" | "kfold";
type BalanceMethod = "undersample" | "smote" | "class_weight" | "none";

const RATIO_OPTIONS = ["90/10", "80/20", "70/30", "60/40"];
const KFOLD_OPTIONS = [3, 4, 5, 6, 7, 8, 9, 10];

// Color convention: blue = Non-Fraud (0), red = Fraud (1)
const BLUE = "bg-blue-500";
const RED = "bg-red-500";

function parseRatio(r: string): { maj: number; min: number } {
  const [a, b] = r.split("/").map((x) => parseInt(x, 10));
  const maj = Number.isFinite(a) ? a : 80;
  const min = Number.isFinite(b) ? b : 20;
  return { maj, min };
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

export default function Step06_BalancingSplit() {
  const { markCompleteAndNext, getNextStepPath } = useWorkflowStore();

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

  const { maj, min } = useMemo(() => parseRatio(balanceRatio), [balanceRatio]);

  const isHoldout = splitStrategy === "holdout";
  const isCV = splitStrategy === "kfold";

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
              onChange={() => setSplitStrategy("holdout")}
            />
            <span className="text-sm font-medium">Holdout (Train/Test)</span>
          </label>

          <label className="flex items-center gap-3 cursor-pointer">
            <input
              id="kfold"
              type="radio"
              checked={isCV}
              onChange={() => setSplitStrategy("kfold")}
            />
            <span className="text-sm font-medium">Cross-validation (Stratified K-Fold)</span>
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
              onChange={(e) => setKFolds(parseInt(e.target.value, 10))}
              className="w-40 p-2 border border-gray-300 rounded-lg"
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
              onChange={(e) => setBalanceRatio(e.target.value)}
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
            <p className="text-xs text-gray-500 mt-1">Only used for undersampling previews.</p>
          </div>

          <div className="col-span-2">
            <label className="block text-sm font-medium text-gray-700 mb-1">Method</label>
            <div className="flex flex-col gap-2">
              <label className="inline-flex items-center gap-2">
                <input
                  type="radio"
                  checked={balanceMethod === "undersample"}
                  onChange={() => setBalanceMethod("undersample")}
                />
                <span>Undersampling</span>
              </label>
              <label className="inline-flex items-center gap-2">
                <input
                  type="radio"
                  checked={balanceMethod === "smote"}
                  onChange={() => setBalanceMethod("smote")}
                />
                <span>SMOTE (if available)</span>
              </label>
              <label className="inline-flex items-center gap-2">
                <input
                  type="radio"
                  checked={balanceMethod === "class_weight"}
                  onChange={() => setBalanceMethod("class_weight")}
                />
                <span>Class Weights</span>
              </label>
              <label className="inline-flex items-center gap-2">
                <input
                  type="radio"
                  checked={balanceMethod === "none"}
                  onChange={() => setBalanceMethod("none")}
                />
                <span>None</span>
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
            onChange={(e) => setBalanceRatio(e.target.value)}
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
