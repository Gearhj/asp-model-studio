import React, { useEffect, useState } from "react";
import StepShell from "../components/StepShell";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { logDecision } from "../lib/decisionJournal";
import { inferLocalColumns, loadLocalDataset, type LocalDataset } from "../lib/localDataset";

const BASE =
  import.meta.env?.VITE_API_BASE?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";
const MISSING_CONFIG_KEY = "modeling-tool-missing-config";

type ColumnInfo = {
  name: string;
  dtype?: string;
  role?: "feature" | "target";
};

type MissingStats = {
  missing: number;
  missingPct: number;
  total: number;
};

type MissingStrategy =
  | "None"
  | "Mean"
  | "Median"
  | "Mode"
  | "Constant"
  | "Drop Row";

type MissingConfig = {
  [col: string]: {
    strategy: MissingStrategy;
    constantValue?: string;
  };
};

export default function Step04_MissingValues() {
  const [columns, setColumns] = useState<ColumnInfo[]>([]);
  const [missingStats, setMissingStats] = useState<Record<string, MissingStats>>({});
  const [usingLocalDataset, setUsingLocalDataset] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [missingConfig, setMissingConfig] = useState<MissingConfig>({});
  const [globalStrategy, setGlobalStrategy] = useState<MissingStrategy>("None");
  const [globalConstantValue, setGlobalConstantValue] = useState("");

  // access store defensively
  const store: any = (useWorkflowStore as any)?.() || {};
  const storeConfig: MissingConfig = store?.missingConfig ?? {};

  useEffect(() => {
    let mounted = true;

    const loadColumns = async () => {
      try {
        let cols: ColumnInfo[] = [];
        let localDataset: LocalDataset | null = null;
        let stats: Record<string, MissingStats> = {};

        try {
          const res = await fetch(`${BASE}/missing/summary`);
          const js = await res.json();
          cols =
            js?.columns?.map((c: any) => ({
              name: c.name ?? c[0] ?? c,
              dtype: c.dtype ?? c[1] ?? undefined,
              role: c.role ?? "feature",
            })) ?? [];
          stats = js?.stats ?? {};
        } catch {
          cols = [];
        }

        if (!cols.length) {
          localDataset = loadLocalDataset();
          if (localDataset?.headers.length) {
            cols = inferLocalColumns(localDataset);
          }
        }

        if (localDataset) {
          for (const col of cols) {
            const values = localDataset.rows.map((row) => row[col.name]);
            const missing = values.filter(
              (value) =>
                value === null ||
                value === undefined ||
                value === "" ||
                (typeof value === "string" && ["na", "n/a", "null", "none", "nan"].includes(value.trim().toLowerCase()))
            ).length;
            stats[col.name] = {
              missing,
              total: localDataset.rows.length,
              missingPct: localDataset.rows.length ? (missing / localDataset.rows.length) * 100 : 0,
            };
          }
        }

        if (!mounted) return;
        setColumns(cols);
        setMissingStats(stats);
        setUsingLocalDataset(Boolean(localDataset));

        // initialise config from store or default to "None"
        const fromStore = Object.keys(storeConfig).length
          ? storeConfig
          : undefined;

        const init: MissingConfig = {};
        cols.forEach((col) => {
          const key = col.name;
          if (fromStore && fromStore[key]) {
            init[key] = { ...fromStore[key] };
          } else {
            init[key] = { strategy: "None" };
          }
        });
        setMissingConfig(init);
      } catch {
        if (!mounted) return;
        setColumns([]);
        setMissingStats({});
        setUsingLocalDataset(false);
      }
    };

    loadColumns();

    return () => {
      mounted = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const featureColumns = columns.filter((c) => c.role !== "target");
  const numericCols = featureColumns.filter((c) =>
    (c.dtype || "").toLowerCase().match(/int|float|double|number|numeric/)
  );
  const categoricalCols = columns.filter(
    (c) =>
      c.role !== "target" &&
      !(c.dtype || "")
        .toLowerCase()
        .match(/int|float|double|number|numeric/)
  );

  const updateStrategy = (col: string, strategy: MissingStrategy) => {
    logDecision({
      workflowStep: "Missing Values",
      actionType: "missing_value_strategy_selected",
      subject: col,
      previousValue: missingConfig[col]?.strategy ?? "None",
      newValue: strategy,
    });
    setMissingConfig((prev) => ({
      ...prev,
      [col]: {
        ...(prev[col] ?? { strategy: "None" }),
        strategy,
      },
    }));
  };

  const updateConstant = (col: string, constantValue: string) => {
    logDecision({
      workflowStep: "Missing Values",
      actionType: "missing_value_strategy_selected",
      subject: `${col} constant value`,
      previousValue: missingConfig[col]?.constantValue ?? "",
      newValue: constantValue,
      followStatus: "not_applicable",
    });
    setMissingConfig((prev) => ({
      ...prev,
      [col]: {
        ...(prev[col] ?? { strategy: "Constant" }),
        strategy: "Constant",
        constantValue,
      },
    }));
  };

  const applyGlobalStrategy = () => {
    logDecision({
      workflowStep: "Missing Values",
      actionType: "missing_value_strategy_selected",
      subject: "All features",
      previousValue: missingConfig,
      newValue: { strategy: globalStrategy, constantValue: globalConstantValue },
    });
    setMissingConfig((prev) => {
      const next: MissingConfig = { ...prev };
      featureColumns.forEach((col) => {
        next[col.name] = {
          ...(next[col.name] ?? { strategy: "None" }),
          strategy: globalStrategy,
          constantValue: globalStrategy === "Constant" ? globalConstantValue : next[col.name]?.constantValue,
        };
      });
      return next;
    });
  };

  // Persist selections to the store on Next (defensive; no-ops if setters missing)
  const persistToStore = async () => {
    localStorage.setItem(MISSING_CONFIG_KEY, JSON.stringify(missingConfig));
    try {
      if (typeof store?.setMissingConfig === "function") {
        store.setMissingConfig(missingConfig);
      } else if (typeof store?.updateMissingConfig === "function") {
        store.updateMissingConfig(missingConfig);
      } else if ("missingConfig" in store) {
        (store as any).missingConfig = missingConfig;
      }
    } catch {
      // swallow; navigation should still work
    }
    const res = await fetch(`${BASE}/missing/apply`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config: missingConfig }),
    });
    const data = await res.json().catch(() => null);
    if (!res.ok || !data?.ok) {
      throw new Error(data?.error || data?.detail || "Missing-value imputation failed.");
    }
    setStatusMessage(
      `Applied missing-value handling. Missing cells before: ${data.missing_before?.toLocaleString?.() ?? data.missing_before}; after: ${data.missing_after?.toLocaleString?.() ?? data.missing_after}.`
    );
  };

  const strategyOptions: MissingStrategy[] = [
    "None",
    "Mean",
    "Median",
    "Mode",
    "Constant",
    "Drop Row",
  ];

  return (
    <StepShell
      title="Step 4: Missing Values"
      subtitle="Review missingness by feature and choose appropriate imputation strategies for numeric and categorical variables."
      nextPath="/step05"
      onNext={persistToStore}
    >
      {usingLocalDataset && (
        <div className="mb-4 rounded border border-blue-200 bg-blue-50 p-3 text-sm text-blue-800">
          Missing-value profiling is using the browser sample from Step 1.
        </div>
      )}
      {columns.length > 0 && (
        <div className="mb-6 flex flex-wrap items-end gap-3 rounded-lg border border-gray-200 bg-gray-50 p-3">
          <label className="grid gap-1">
            <span className="text-xs font-medium text-gray-600">Global missing-value strategy</span>
            <select
              className="w-56 rounded-lg border border-gray-300 bg-white p-2 text-sm"
              value={globalStrategy}
              onChange={(e) => setGlobalStrategy(e.target.value as MissingStrategy)}
            >
              {strategyOptions.map((opt) => (
                <option key={opt} value={opt}>
                  {opt}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1">
            <span className="text-xs font-medium text-gray-600">Global constant</span>
            <input
              className="w-44 rounded-lg border border-gray-300 bg-white p-2 text-sm disabled:bg-gray-100"
              placeholder="If Constant"
              value={globalConstantValue}
              onChange={(e) => setGlobalConstantValue(e.target.value)}
              disabled={globalStrategy !== "Constant"}
            />
          </label>
          <button
            type="button"
            onClick={applyGlobalStrategy}
            className="rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-indigo-700"
          >
            Apply to All Features
          </button>
          <div className="text-xs text-gray-500">
            Apply a default strategy globally, then override individual features in the tables.
          </div>
        </div>
      )}
      {statusMessage && (
        <div className="mb-4 rounded border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">
          {statusMessage}
        </div>
      )}
      <div className="grid gap-6 md:grid-cols-2">
        {/* Numeric Features */}
        <div className="bg-white border rounded-lg p-4">
          <h3 className="font-semibold mb-2">Numeric Features</h3>
          {numericCols.length === 0 ? (
            <p className="text-sm text-gray-500">
              No numeric features detected. Load a CSV in Step 1 if this is unexpected.
            </p>
          ) : (
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left">
                  <th className="px-2 py-1 border-b">Feature</th>
                  <th className="px-2 py-1 border-b">Missing</th>
                  <th className="px-2 py-1 border-b">Missing %</th>
                  <th className="px-2 py-1 border-b">Strategy</th>
                  <th className="px-2 py-1 border-b">Constant</th>
                </tr>
              </thead>
              <tbody>
                {numericCols.map((col) => {
                  const cfg = missingConfig[col.name] ?? {
                    strategy: "None" as MissingStrategy,
                  };
                  const stats = missingStats[col.name];
                  return (
                    <tr key={col.name} className="odd:bg-gray-50">
                      <td className="px-2 py-1 border-b">{col.name}</td>
                      <td className="px-2 py-1 border-b">{stats ? stats.missing.toLocaleString() : "—"}</td>
                      <td className="px-2 py-1 border-b">{stats ? `${stats.missingPct.toFixed(2)}%` : "—"}</td>
                      <td className="px-2 py-1 border-b">
                        <select
                          className="w-full border rounded-md px-2 py-1"
                          value={cfg.strategy}
                          onChange={(e) =>
                            updateStrategy(
                              col.name,
                              e.target.value as MissingStrategy
                            )
                          }
                        >
                          {strategyOptions.map((opt) => (
                            <option key={opt} value={opt}>
                              {opt}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="px-2 py-1 border-b">
                        <input
                          className="w-full border rounded-md px-2 py-1 text-xs"
                          placeholder="Only used if Constant"
                          value={cfg.constantValue ?? ""}
                          onChange={(e) =>
                            updateConstant(col.name, e.target.value)
                          }
                          disabled={cfg.strategy !== "Constant"}
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Categorical Features */}
        <div className="bg-white border rounded-lg p-4">
          <h3 className="font-semibold mb-2">Categorical Features</h3>
          {categoricalCols.length === 0 ? (
            <p className="text-sm text-gray-500">
              No categorical features detected. Load a CSV in Step 1 if this is unexpected.
            </p>
          ) : (
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left">
                  <th className="px-2 py-1 border-b">Feature</th>
                  <th className="px-2 py-1 border-b">Missing</th>
                  <th className="px-2 py-1 border-b">Missing %</th>
                  <th className="px-2 py-1 border-b">Strategy</th>
                  <th className="px-2 py-1 border-b">Constant</th>
                </tr>
              </thead>
              <tbody>
                {categoricalCols.map((col) => {
                  const cfg = missingConfig[col.name] ?? {
                    strategy: "None" as MissingStrategy,
                  };
                  const stats = missingStats[col.name];
                  return (
                    <tr key={col.name} className="odd:bg-gray-50">
                      <td className="px-2 py-1 border-b">{col.name}</td>
                      <td className="px-2 py-1 border-b">{stats ? stats.missing.toLocaleString() : "—"}</td>
                      <td className="px-2 py-1 border-b">{stats ? `${stats.missingPct.toFixed(2)}%` : "—"}</td>
                      <td className="px-2 py-1 border-b">
                        <select
                          className="w-full border rounded-md px-2 py-1"
                          value={cfg.strategy}
                          onChange={(e) =>
                            updateStrategy(
                              col.name,
                              e.target.value as MissingStrategy
                            )
                          }
                        >
                          {strategyOptions.map((opt) => (
                            <option key={opt} value={opt}>
                              {opt}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="px-2 py-1 border-b">
                        <input
                          className="w-full border rounded-md px-2 py-1 text-xs"
                          placeholder="Only used if Constant"
                          value={cfg.constantValue ?? ""}
                          onChange={(e) =>
                            updateConstant(col.name, e.target.value)
                          }
                          disabled={cfg.strategy !== "Constant"}
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </StepShell>
  );
}
