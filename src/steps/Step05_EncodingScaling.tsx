import React, { useEffect, useMemo, useState } from "react";
import StepShell from "../components/StepShell";
// We will safely use the store if it exists. If the shape differs, guards prevent throws.
import { useWorkflowStore } from "../state/useWorkflowStore";
import { inferLocalColumns, loadLocalDataset } from "../lib/localDataset";

/**
 * Step 5 — Feature Engineering (Encoding & Scaling)
 * - Polynomial features (degree 2/3)
 * - Scaling (Standard / MinMax / None)
 * - Interaction builder (left * right)
 * - Numeric → categorical binning
 * - Rule-based categorical features
 * - Live preview (first 10 rows) using server sample when available, with synthetic fallback
 *
 * Navigation: bottom button -> /step06 (Balancing & Split)
 * Persist: tries to write to store.featureBuilder if available; otherwise no-op
 */

// ---------------------- Helpers ----------------------
const BASE =
  import.meta.env?.VITE_API_BASE?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

type ColumnInfo = { name: string; dtype?: string };
type Interaction = { left: string; right: string; newName: string };
type BinFeature = {
  source: string;
  thresholds: number[];
  labels: string[];
  newName: string;
  treatMissingAsCategory?: boolean;
};
type RuleWhen = { op: string; value: string };
type RuleRow = { op: string; value: string; thenLabel: string };
type RuleFeature = {
  source: string;
  rules: { when: RuleWhen; thenLabel: string }[];
  elseLabel: string;
  newName: string;
};
type Transforms = { poly: string; scaler: string; encoding: string };

type FeatureBuilderState = {
  interactions: Interaction[];
  bins: BinFeature[];
  rules: RuleFeature[];
  transforms: Transforms;
};

type AnyRow = Record<string, any>;
type LoadedDatasetContext = { columns: ColumnInfo[]; target: string | null; rows: AnyRow[] };
const FEATURE_CONFIG_KEY = "modeling-tool-feature-builder";
const transformGuidance = {
  poly: {
    None: "Definition: do not create polynomial terms. Use when relationships are mostly linear or model complexity should stay low.",
    "Degree 2": "Definition: add squared terms. Use when a numeric feature may have a curved relationship with the target.",
    "Degree 3": "Definition: add squared and cubed terms. Use only when nonlinear signal is expected and overfitting risk is controlled.",
  },
  scaler: {
    None: "Definition: keep numeric values on their original scale. Use for tree-based models or already standardized features.",
    StandardScaler: "Definition: center and scale to z-scores. Use for logistic regression, SVM, KNN, and PCA-like distance calculations.",
    MinMaxScaler: "Definition: rescale numeric values to a fixed range. Use for neural nets or distance models when bounded inputs help.",
  },
  encoding: {
    None: "Definition: do not encode categoricals here. Use when no categorical fields exist or the backend/model handles them.",
    "One-Hot": "Definition: create one binary indicator per category. Use for nominal categories with no natural order.",
    Label: "Definition: convert categories to integer codes. Use only for ordinal fields or models that can safely treat codes as labels.",
  },
} as const;

// simple utilities
const uniq = (arr: string[]) => Array.from(new Set(arr.filter(Boolean)));
const parseNumberList = (txt: string) =>
  txt
    .split(",")
    .map((t) => parseFloat(t.trim()))
    .filter((v) => Number.isFinite(v))
    .sort((a, b) => a - b);

function loadFeatureBuilderConfig(): FeatureBuilderState | null {
  if (typeof localStorage === "undefined") return null;
  try {
    const parsed = JSON.parse(localStorage.getItem(FEATURE_CONFIG_KEY) || "null") as Partial<FeatureBuilderState> | null;
    if (!parsed || typeof parsed !== "object") return null;
    return {
      interactions: Array.isArray(parsed.interactions) ? (parsed.interactions as Interaction[]) : [],
      bins: Array.isArray(parsed.bins) ? (parsed.bins as BinFeature[]) : [],
      rules: Array.isArray(parsed.rules) ? (parsed.rules as RuleFeature[]) : [],
      transforms: parsed.transforms ?? { poly: "None", scaler: "None", encoding: "None" },
    };
  } catch {
    return null;
  }
}

function filterRowsToHeaders(rows: AnyRow[], headers: string[]) {
  if (!headers.length) return rows;
  return rows.map((row) => {
    const filtered: AnyRow = {};
    headers.forEach((header) => {
      filtered[header] = row?.[header];
    });
    return filtered;
  });
}

// ---------------------- Component ----------------------
export default function Step05_EncodingScaling() {
  // ---- columns (from server if available) ----
  const [columns, setColumns] = useState<ColumnInfo[]>([]);
  const [targetColumn, setTargetColumn] = useState<string | null>(null);
  const featureColumns = useMemo(() => columns.filter((column) => column.name !== targetColumn), [columns, targetColumn]);
  const featureColumnNames = useMemo(() => new Set(featureColumns.map((column) => column.name)), [featureColumns]);
  const numericCols = useMemo(
    () =>
      featureColumns
        .filter((c) =>
          (c.dtype || "").toLowerCase().match(/int|float|double|number|numeric/)
        )
        .map((c) => c.name),
    [featureColumns]
  );
  const categoricalCols = useMemo(
    () =>
      featureColumns
        .filter((c) => !(c.dtype || "").toLowerCase().match(/int|float|double|number|numeric/))
        .map((c) => c.name),
    [featureColumns]
  );

  // ---- sample data for preview ----
  const [sample, setSample] = useState<AnyRow[]>([]);
  const [usingLocalDataset, setUsingLocalDataset] = useState(false);

  // ---- store (defensive) ----
  const store = (useWorkflowStore as any)?.() || {};
  const savedFB = loadFeatureBuilderConfig();
  const storeFeatureBuilder = store?.featureBuilder as Partial<FeatureBuilderState> | undefined;
  const storeHasFeatureBuilder =
    !!storeFeatureBuilder &&
    ((storeFeatureBuilder.interactions?.length ?? 0) > 0 ||
      (storeFeatureBuilder.bins?.length ?? 0) > 0 ||
      (storeFeatureBuilder.rules?.length ?? 0) > 0 ||
      !!storeFeatureBuilder.transforms);
  const storeFB: FeatureBuilderState = storeHasFeatureBuilder
    ? {
        interactions: storeFeatureBuilder?.interactions ?? [],
        bins: storeFeatureBuilder?.bins ?? [],
        rules: storeFeatureBuilder?.rules ?? [],
        transforms: storeFeatureBuilder?.transforms ?? { poly: "None", scaler: "None", encoding: "None" },
      }
    : savedFB ?? {
        interactions: [],
        bins: [],
        rules: [],
        transforms: { poly: "None", scaler: "None", encoding: "None" },
      };

  // ---- local working state (starts from store snapshot) ----
  const [interactions, setInteractions] = useState<Interaction[]>(
    storeFB.interactions ?? []
  );
  const [bins, setBins] = useState<BinFeature[]>(storeFB.bins ?? []);
  const [rules, setRules] = useState<RuleFeature[]>(storeFB.rules ?? []);
  const [transforms, setTransforms] = useState<Transforms>(
    storeFB.transforms ?? { poly: "None", scaler: "None", encoding: "None" }
  );

  // ---- UI local controls ----
  // interactions
  const [ixLeft, setIxLeft] = useState<string>("");
  const [ixRight, setIxRight] = useState<string>("");
  const [ixName, setIxName] = useState<string>("");

  // numeric → categorical
  const [binSource, setBinSource] = useState<string>("");
  const [binThresholds, setBinThresholds] = useState<string>("200,600");
  const [binLabels, setBinLabels] = useState<string>("Low,Medium,High");
  const [binName, setBinName] = useState<string>("feature_bin");
  const [binTreatMissing, setBinTreatMissing] = useState<boolean>(true);

  // rule-based categorical
  const [ruleSource, setRuleSource] = useState<string>("");
  const [ruleName, setRuleName] = useState<string>("rule_feature");
  const [elseLabel, setElseLabel] = useState<string>("Other");
  const [ruleRows, setRuleRows] = useState<RuleRow[]>([
    { op: "CONTAINS", value: "Travel", thenLabel: "TravelRelated" },
  ]);

  useEffect(() => {
    if (!featureColumnNames.size) return;
    setInteractions((current) => current.filter((item) => featureColumnNames.has(item.left) && featureColumnNames.has(item.right)));
    setBins((current) => current.filter((item) => featureColumnNames.has(item.source)));
    setRules((current) => current.filter((item) => featureColumnNames.has(item.source)));
    setIxLeft((current) => (current && !featureColumnNames.has(current) ? "" : current));
    setIxRight((current) => (current && !featureColumnNames.has(current) ? "" : current));
    setBinSource((current) => (current && !featureColumnNames.has(current) ? "" : current));
    setRuleSource((current) => (current && !featureColumnNames.has(current) ? "" : current));
  }, [featureColumnNames]);

  // initial fetch: columns + sample
  useEffect(() => {
    let mounted = true;
    let datasetContextPromise: Promise<LoadedDatasetContext> | null = null;

    const loadDatasetContext = async (): Promise<LoadedDatasetContext> => {
      if (datasetContextPromise) return datasetContextPromise;
      datasetContextPromise = (async () => {
        const localDataset = loadLocalDataset();
        let rows: AnyRow[] = [];
        let target = localDataset?.target ?? null;
        let cols: ColumnInfo[] = [];

        try {
          const sampleResponse = await fetch(`${BASE}/data/get_sample`);
          const sampleJson = await sampleResponse.json();
          rows = Array.isArray(sampleJson?.rows) ? sampleJson.rows : [];
          target = sampleJson?.target ?? sampleJson?.metadata?.target ?? target;
        } catch {
          rows = [];
        }

        if (!rows.length) rows = localDataset?.rows.slice(0, 10) ?? [];

        try {
          const columnResponse = await fetch(`${BASE}/columns`);
          const columnJson = await columnResponse.json();
          cols =
            columnJson?.columns?.map((c: any) => ({
              name: c.name ?? c[0] ?? c,
              dtype: c.dtype ?? c[1] ?? undefined,
            })) ?? [];
          target = columnJson?.target ?? columnJson?.metadata?.target ?? target;
        } catch {
          cols = [];
        }

        if (!cols.length && localDataset?.headers.length) cols = inferLocalColumns(localDataset);
        if (!cols.length && rows.length) {
          cols = Object.keys(rows[0]).map((name) => ({
            name,
            dtype: rows.some((row) => Number.isFinite(Number(row[name]))) ? "float64" : "object",
          }));
        }

        if (localDataset?.headers.length) {
          const allowedHeaders = new Set(localDataset.headers);
          target = localDataset.target ?? target;
          cols = cols.filter((column) => allowedHeaders.has(column.name));
          rows = filterRowsToHeaders(rows, localDataset.headers);
        }

        return { columns: cols, target, rows };
      })();
      return datasetContextPromise;
    };

    const loadColumns = async () => {
      try {
        const context = await loadDatasetContext();
        const cols = context.columns;

        // Expect js.columns = [{name,dtype}, ...] or similar
        if (!mounted) return;
        setColumns(cols);
        setTargetColumn(context.target);
        setUsingLocalDataset(!!loadLocalDataset()?.headers.length && !context.rows.length);

        // pick sensible defaults after columns known
        if (cols.length) {
          const featureCols = cols.filter((column) => column.name !== context.target);
          const nums = featureCols
            .filter((c) =>
              (c.dtype || "").toLowerCase().match(/int|float|double|number|numeric/)
            )
            .map((c) => c.name);
          const cats = featureCols
            .filter(
              (c) =>
                !(c.dtype || "")
                  .toLowerCase()
                  .match(/int|float|double|number|numeric/)
            )
            .map((c) => c.name);

          setIxLeft((prev) => prev || nums[0] || "");
          setIxRight((prev) => prev || nums[1] || nums[0] || "");
          setBinSource((prev) => prev || nums[0] || "");
          setRuleSource((prev) => prev || cats[0] || nums[0] || "");
        }
      } catch {
        // non-fatal
      }
    };

    const loadSample = async () => {
      try {
        const context = await loadDatasetContext();
        const rows = context.rows;

        if (!mounted) return;
        setTargetColumn(context.target);
        if (rows.length) setSample(rows.slice(0, 10));
        else setSample(syntheticFallback());
      } catch {
        if (!mounted) return;
        setSample(syntheticFallback());
      }
    };

    loadColumns();
    loadSample();
    return () => {
      mounted = false;
    };
  }, []);

  // synthetic sample when the server returns nothing
  const syntheticFallback = (): AnyRow[] => {
    // Make a tiny generic demo sample so preview never breaks
    const rows: AnyRow[] = [];
    for (let i = 0; i < 10; i++) {
      rows.push({
        distance_from_home: Math.round(Math.random() * 1200),
        distance_from_last_transaction: Math.round(Math.random() * 800),
        ratio_to_median_purchase_price: +(Math.random() * 10).toFixed(2),
        repeat_retailer: Math.random() > 0.5 ? 1 : 0,
        used_chip: Math.random() > 0.5 ? 1 : 0,
        used_pin_number: Math.random() > 0.5 ? 1 : 0,
        online_order: Math.random() > 0.5 ? 1 : 0,
        merchant_category: ["Retail", "Food", "Travel", "Entertainment"][
          Math.floor(Math.random() * 4)
        ],
      });
    }
    return rows;
  };

  // ------- handlers: transforms -------
  const setPoly = (v: string) =>
    setTransforms((t) => ({ ...t, poly: v }));
  const setScaler = (v: string) =>
    setTransforms((t) => ({ ...t, scaler: v }));
  const setEncoding = (v: string) =>
    setTransforms((t) => ({ ...t, encoding: v }));

  // ------- handlers: interactions -------
  const addInteraction = () => {
    if (!ixLeft || !ixRight || ixLeft === ixRight) return;
    const newName = ixName || `${ixLeft}_x_${ixRight}`;
    if (interactions.find((x) => x.newName === newName)) return;
    setInteractions((arr) => [...arr, { left: ixLeft, right: ixRight, newName }]);
    setIxName("");
  };
  const removeInteraction = (name: string) =>
    setInteractions((arr) => arr.filter((x) => x.newName !== name));

  // ------- handlers: bins -------
  const addBin = () => {
    if (!binSource) return;
    const th = parseNumberList(binThresholds);
    const labs = uniq(binLabels.split(",").map((s) => s.trim()));
    if (labs.length !== th.length + 1) return; // invalid config
    const newName = binName || `${binSource}_bin`;
    if (bins.find((b) => b.newName === newName)) return;
    setBins((arr) => [
      ...arr,
      {
        source: binSource,
        thresholds: th,
        labels: labs,
        newName,
        treatMissingAsCategory: binTreatMissing,
      },
    ]);
  };
  const removeBin = (name: string) =>
    setBins((arr) => arr.filter((b) => b.newName !== name));

  // ------- handlers: rules -------
  const addRuleRow = () =>
    setRuleRows((r) => [...r, { op: "=", value: "", thenLabel: "" }]);
  const updateRuleRow = (i: number, key: keyof RuleRow, val: string) =>
    setRuleRows((rows) => rows.map((r, idx) => (idx === i ? { ...r, [key]: val } : r)));
  const deleteRuleRow = (i: number) =>
    setRuleRows((rows) => rows.filter((_, idx) => idx !== i));
  const addRuleFeature = () => {
    if (!ruleName || !ruleSource) return;
    const valid = ruleRows.filter((r) => r.value?.length && r.thenLabel?.length);
    if (!valid.length) return;
    const newFeature: RuleFeature = {
      source: ruleSource,
      rules: valid.map((r) => ({ when: { op: r.op, value: r.value }, thenLabel: r.thenLabel })),
      elseLabel,
      newName: ruleName,
    };
    if (rules.find((r) => r.newName === newFeature.newName)) return;
    setRules((arr) => [...arr, newFeature]);
  };
  const removeRuleFeature = (name: string) =>
    setRules((arr) => arr.filter((r) => r.newName !== name));

  // ------- preview -------
  const preview: AnyRow[] = useMemo(() => {
    if (!sample.length) return [];
    // shallow copy
    const out = sample.map((r) => ({ ...r }));

    // polynomials (simple demo: square a couple of numeric columns if present)
    if (transforms.poly !== "None") {
      const nums = numericCols.filter((k) => typeof out[0]?.[k] === "number");
      nums.slice(0, 2).forEach((k) => {
        out.forEach((row) => {
          const v = Number(row[k]);
          if (Number.isFinite(v)) {
            row[`${k}^2`] = +(v * v).toFixed(4);
            if (transforms.poly === "Degree 3") {
              row[`${k}^3`] = +(v * v * v).toFixed(4);
            }
          }
        });
      });
    }

    // scaling (demo preview only)
    if (transforms.scaler !== "None") {
      const nums = numericCols.filter((k) => typeof out[0]?.[k] === "number");
      nums.slice(0, 2).forEach((k) => {
        const vals = out.map((r) => Number(r[k] ?? 0));
        const mean =
          vals.reduce((s, x) => s + x, 0) / Math.max(1, vals.length);
        const std =
          Math.sqrt(
            vals.reduce((s, x) => s + (x - mean) ** 2, 0) /
              Math.max(1, vals.length)
          ) || 1;
        const max = Math.max(...vals, 1);
        out.forEach((row, i) => {
          const v = Number(row[k] ?? 0);
          row[
            transforms.scaler === "StandardScaler" ? `${k}_z` : `${k}_minmax`
          ] =
            transforms.scaler === "StandardScaler"
              ? +((v - mean) / std).toFixed(4)
              : +(v / max).toFixed(4);
        });
      });
    }

    // one-hot (demo preview only)
    if (transforms.encoding !== "None") {
      const catKey =
        categoricalCols[0] ||
        Object.keys(out[0]).find((k) => featureColumnNames.has(k) && typeof out[0][k] === "string");
      if (catKey) {
        const cats = uniq(out.map((r) => String(r[catKey])));
        cats.slice(0, 4).forEach((c) => {
          out.forEach((r) => {
            r[`${catKey}==${c}`] = r[catKey] === c ? 1 : 0;
          });
        });
      }
    }

    // interactions
    interactions.forEach((ix) => {
      out.forEach((r) => {
        const a = Number(r[ix.left]);
        const b = Number(r[ix.right]);
        r[ix.newName] = Number.isFinite(a) && Number.isFinite(b) ? +(a * b).toFixed(4) : null;
      });
    });

    // bins
    bins.forEach((b) => {
      out.forEach((r) => {
        const v = r[b.source];
        if (v == null || v === "") {
          r[b.newName] = b.treatMissingAsCategory ? "Missing" : "";
          return;
        }
        const val = Number(v);
        let idx = 0;
        while (idx < b.thresholds.length && val >= b.thresholds[idx]) idx++;
        r[b.newName] = b.labels[idx] ?? b.labels[b.labels.length - 1] ?? "";
      });
    });

    // rule features
    rules.forEach((rf) => {
      out.forEach((r) => {
        const v = r[rf.source];
        let label = rf.elseLabel;
        rf.rules.forEach((ru) => {
          const op = (ru.when.op || "").toUpperCase();
          const tgt = ru.when.value ?? "";
          const ok =
            op === "CONTAINS"
              ? String(v ?? "").includes(tgt)
              : op === "IN"
              ? tgt
                  .split(",")
                  .map((s) => s.trim())
                  .includes(String(v ?? ""))
              : op === "NOT IN"
              ? !tgt
                  .split(",")
                  .map((s) => s.trim())
                  .includes(String(v ?? ""))
              : op === "="
              ? String(v ?? "") === tgt
              : op === "!="
              ? String(v ?? "") !== tgt
              : op === ">"
              ? Number(v) > Number(tgt)
              : op === ">="
              ? Number(v) >= Number(tgt)
              : op === "<"
              ? Number(v) < Number(tgt)
              : op === "<="
              ? Number(v) <= Number(tgt)
              : false;
          if (ok) label = ru.thenLabel;
        });
        r[rf.newName] = label;
      });
    });

    return out;
  }, [sample, transforms, interactions, bins, rules, categoricalCols, numericCols, featureColumnNames]);

  // columns to render in preview
  const previewCols = useMemo(
    () => (preview[0] ? Object.keys(preview[0]) : []),
    [preview]
  );

  useEffect(() => {
    const payload: FeatureBuilderState = {
      interactions: interactions.filter((item) => featureColumnNames.has(item.left) && featureColumnNames.has(item.right)),
      bins: bins.filter((item) => featureColumnNames.has(item.source)),
      rules: rules.filter((item) => featureColumnNames.has(item.source)),
      transforms,
    };
    try {
      localStorage.setItem(FEATURE_CONFIG_KEY, JSON.stringify(payload));
    } catch {
      // Keep the page state visible even if browser storage is full.
    }
  }, [interactions, bins, rules, transforms, featureColumnNames]);

  // persist current selections to the store (defensive: try several common setter names)
  const persistToStore = async () => {
    const payload: FeatureBuilderState = {
      interactions: interactions.filter((item) => featureColumnNames.has(item.left) && featureColumnNames.has(item.right)),
      bins: bins.filter((item) => featureColumnNames.has(item.source)),
      rules: rules.filter((item) => featureColumnNames.has(item.source)),
      transforms,
    };

    try {
      localStorage.setItem(FEATURE_CONFIG_KEY, JSON.stringify(payload));
      if (typeof store?.setFeatureBuilder === "function") {
        store.setFeatureBuilder(payload);
      } else if (typeof store?.updateFeatureBuilder === "function") {
        store.updateFeatureBuilder(payload);
      } else if (typeof store?.updateTransforms === "function") {
        // split saves if only specific setters exist
        store.updateTransforms(transforms);
        if (typeof store?.setInteractions === "function")
          store.setInteractions(interactions);
        if (typeof store?.setBins === "function") store.setBins(bins);
        if (typeof store?.setRules === "function") store.setRules(rules);
      } else {
        // last resort: direct assign if store.featureBuilder exists (not ideal, but guarded)
        if (store && "featureBuilder" in store) {
          (store as any).featureBuilder = payload;
        }
      }
    } catch {
      // swallow; UI remains usable
    }
  };

  return (
    <StepShell
      title="Step 5: Feature Engineering (Encoding & Scaling)"
      subtitle="Create polynomials, scale numeric features, build interactions, convert numeric to categories, and define rule-based categorical features. Preview updates on the first 10 rows."
      nextPath="/step06"
      onNext={persistToStore}
    >
      {usingLocalDataset && (
        <div className="mb-4 rounded border border-blue-200 bg-blue-50 p-3 text-sm text-blue-800">
          Feature controls are using the browser sample from Step 1.
        </div>
      )}
      {/* Top controls: Polynomials / Scaling / Encoding */}
      <div className="grid gap-4 md:grid-cols-3 mb-6">
        <div className="bg-white border rounded-lg p-4">
          <h3 className="font-semibold mb-2">Polynomials</h3>
          <select
            className="w-full border rounded-md px-3 py-2"
            value={transforms.poly}
            onChange={(e) => setPoly(e.target.value)}
            title={transformGuidance.poly[transforms.poly as keyof typeof transformGuidance.poly]}
          >
            <option>None</option>
            <option>Degree 2</option>
            <option>Degree 3</option>
          </select>
          <p className="text-sm text-gray-500 mt-2">
            {transformGuidance.poly[transforms.poly as keyof typeof transformGuidance.poly]}
          </p>
        </div>

        <div className="bg-white border rounded-lg p-4">
          <h3 className="font-semibold mb-2">Scaling</h3>
          <select
            className="w-full border rounded-md px-3 py-2"
            value={transforms.scaler}
            onChange={(e) => setScaler(e.target.value)}
            title={transformGuidance.scaler[transforms.scaler as keyof typeof transformGuidance.scaler]}
          >
            <option>None</option>
            <option>StandardScaler</option>
            <option>MinMaxScaler</option>
          </select>
          <p className="text-sm text-gray-500 mt-2">
            {transformGuidance.scaler[transforms.scaler as keyof typeof transformGuidance.scaler]}
          </p>
          <p className="text-sm text-gray-500 mt-2">
            Shows z-scores or min–max scaled columns (preview only).
          </p>
        </div>

        <div className="bg-white border rounded-lg p-4">
          <h3 className="font-semibold mb-2">Encoding</h3>
          <select
            className="w-full border rounded-md px-3 py-2"
            value={transforms.encoding}
            onChange={(e) => setEncoding(e.target.value)}
            title={transformGuidance.encoding[transforms.encoding as keyof typeof transformGuidance.encoding]}
          >
            <option>None</option>
            <option>One-Hot</option>
            <option>Label</option>
          </select>
          <p className="text-sm text-gray-500 mt-2">
            {transformGuidance.encoding[transforms.encoding as keyof typeof transformGuidance.encoding]}
          </p>
          <p className="text-sm text-gray-500 mt-2">
            One-Hot preview uses the first categorical column if available.
          </p>
        </div>
      </div>

      {/* Interactions */}
      <div className="bg-white border rounded-lg p-4 mb-6">
        <h3 className="font-semibold mb-3">Interaction Terms</h3>
        <div className="grid gap-3 md:grid-cols-4">
          <select
            className="border rounded-md px-3 py-2"
            value={ixLeft}
            onChange={(e) => setIxLeft(e.target.value)}
          >
            <option value="">Select left</option>
            {numericCols.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <select
            className="border rounded-md px-3 py-2"
            value={ixRight}
            onChange={(e) => setIxRight(e.target.value)}
          >
            <option value="">Select right</option>
            {numericCols.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <input
            className="border rounded-md px-3 py-2"
            placeholder="New name (auto if blank)"
            value={ixName}
            onChange={(e) => setIxName(e.target.value)}
          />
          <button
            className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-md px-3 py-2"
            onClick={addInteraction}
          >
            Add
          </button>
        </div>

        {interactions.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {interactions.map((ix) => (
              <span
                key={ix.newName}
                className="border rounded-full px-3 py-1 text-sm flex items-center gap-2"
              >
                {ix.newName} <span className="text-gray-400">= {ix.left} × {ix.right}</span>
                <button
                  className="text-red-600"
                  onClick={() => removeInteraction(ix.newName)}
                  title="Remove"
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Numeric → categorical */}
      <div className="bg-white border rounded-lg p-4 mb-6">
        <h3 className="font-semibold mb-3">Numeric → Categorical (Binning)</h3>
        <div className="grid gap-3 md:grid-cols-5">
          <select
            className="border rounded-md px-3 py-2"
            value={binSource}
            onChange={(e) => setBinSource(e.target.value)}
          >
            <option value="">Source</option>
            {numericCols.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <input
            className="border rounded-md px-3 py-2"
            placeholder="Thresholds (e.g., 200,600)"
            value={binThresholds}
            onChange={(e) => setBinThresholds(e.target.value)}
          />
          <input
            className="border rounded-md px-3 py-2"
            placeholder="Labels (e.g., Low,Medium,High)"
            value={binLabels}
            onChange={(e) => setBinLabels(e.target.value)}
          />
          <input
            className="border rounded-md px-3 py-2"
            placeholder="New name (default: <source>_bin)"
            value={binName}
            onChange={(e) => setBinName(e.target.value)}
          />
          <button
            className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-md px-3 py-2"
            onClick={addBin}
          >
            Add
          </button>
        </div>
        <label className="mt-2 flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={binTreatMissing}
            onChange={(e) => setBinTreatMissing(e.target.checked)}
          />
          Treat missing as a category
        </label>

        {bins.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {bins.map((b) => (
              <span
                key={b.newName}
                className="border rounded-full px-3 py-1 text-sm flex items-center gap-2"
              >
                {b.newName}
                <button
                  className="text-red-600"
                  onClick={() => removeBin(b.newName)}
                  title="Remove"
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Rule-based categorical feature */}
      <div className="bg-white border rounded-lg p-4 mb-6">
        <h3 className="font-semibold mb-3">Rule-based Categorical Feature</h3>
        <div className="grid gap-3 md:grid-cols-4 mb-2">
          <select
            className="border rounded-md px-3 py-2"
            value={ruleSource}
            onChange={(e) => setRuleSource(e.target.value)}
          >
            <option value="">Source column</option>
            {uniq([...categoricalCols, ...numericCols]).map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <input
            className="border rounded-md px-3 py-2"
            placeholder="New feature name"
            value={ruleName}
            onChange={(e) => setRuleName(e.target.value)}
          />
          <input
            className="border rounded-md px-3 py-2"
            placeholder="Else label (default)"
            value={elseLabel}
            onChange={(e) => setElseLabel(e.target.value)}
          />
          <button
            className="bg-indigo-600 hover:bg-indigo-700 text-white rounded-md px-3 py-2"
            onClick={addRuleFeature}
          >
            Add Feature
          </button>
        </div>

        {ruleRows.map((r, i) => (
          <div key={i} className="grid gap-2 md:grid-cols-6 mb-2">
            <select
              className="border rounded-md px-3 py-2"
              value={r.op}
              onChange={(e) => updateRuleRow(i, "op", e.target.value)}
            >
              {["=", "!=", ">", ">=", "<", "<=", "IN", "NOT IN", "CONTAINS"].map(
                (op) => (
                  <option key={op}>{op}</option>
                )
              )}
            </select>
            <input
              className="border rounded-md px-3 py-2 md:col-span-3"
              placeholder="Value (comma-list for IN / NOT IN)"
              value={r.value}
              onChange={(e) => updateRuleRow(i, "value", e.target.value)}
            />
            <input
              className="border rounded-md px-3 py-2"
              placeholder="Then label"
              value={r.thenLabel}
              onChange={(e) => updateRuleRow(i, "thenLabel", e.target.value)}
            />
            <button
              className="text-red-600 text-sm"
              onClick={() => deleteRuleRow(i)}
              title="Remove this condition row"
            >
              Remove
            </button>
          </div>
        ))}
        <button
          className="border rounded-md px-3 py-2 text-sm"
          onClick={addRuleRow}
        >
          + Add rule row
        </button>

        {rules.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {rules.map((rf) => (
              <span
                key={rf.newName}
                className="border rounded-full px-3 py-1 text-sm flex items-center gap-2"
              >
                {rf.newName}
                <button
                  className="text-red-600"
                  onClick={() => removeRuleFeature(rf.newName)}
                  title="Remove"
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Preview */}
      <div className="bg-white border rounded-lg p-4">
        <h3 className="font-semibold mb-3">Preview (first 10 rows)</h3>
        <div className="overflow-auto">
          {preview.length === 0 ? (
            <p className="text-sm text-gray-500">No preview rows available.</p>
          ) : (
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left">
                  {previewCols.map((c) => (
                    <th key={c} className="px-2 py-1 border-b">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {preview.map((row, i) => (
                  <tr key={i} className="odd:bg-gray-50">
                    {previewCols.map((c) => (
                      <td key={c} className="px-2 py-1 border-b">
                        {String(row[c])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </StepShell>
  );
}
