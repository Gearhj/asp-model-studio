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
const VIF_EXCLUDED_FEATURES_KEY = "modeling-tool-vif-excluded-features";
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

function solveLinearSystem(matrix: number[][], vector: number[]) {
  const n = vector.length;
  const a = matrix.map((row, i) => [...row, vector[i]]);
  for (let i = 0; i < n; i += 1) {
    let pivot = i;
    for (let r = i + 1; r < n; r += 1) {
      if (Math.abs(a[r][i]) > Math.abs(a[pivot][i])) pivot = r;
    }
    if (Math.abs(a[pivot][i]) < 1e-10) return null;
    [a[i], a[pivot]] = [a[pivot], a[i]];
    const divisor = a[i][i];
    for (let c = i; c <= n; c += 1) a[i][c] /= divisor;
    for (let r = 0; r < n; r += 1) {
      if (r === i) continue;
      const factor = a[r][i];
      for (let c = i; c <= n; c += 1) a[r][c] -= factor * a[i][c];
    }
  }
  return a.map((row) => row[n]);
}

const VIF_EXCLUDED_FIELD_PATTERN = /(^|_)(row|record|index|id|split|fold|target|actual|score|probability|prediction|predicted|residual|error|decile|diagnostic|output|rank)($|_)/i;
const VIF_MISSINGNESS_THRESHOLD = 0.4;
const VIF_AUTO_EXCLUDE_THRESHOLD = 10;

function vifEligibilityReason(column: string, rows: AnyRow[]) {
  if (VIF_EXCLUDED_FIELD_PATTERN.test(column)) return "Diagnostic/output field";
  const numericValues = rows.map((row) => Number(row[column])).filter(Number.isFinite);
  if (!rows.length) return "Not enough rows";
  const missingRate = 1 - numericValues.length / rows.length;
  if (missingRate > VIF_MISSINGNESS_THRESHOLD) return "Too many missing values";
  if (numericValues.length < 3) return "Not enough rows";
  const unique = new Set(numericValues.map((value) => value.toFixed(12)));
  if (unique.size <= 1) return "Constant variable";
  return null;
}

function previewVifDiagnostics(rows: AnyRow[], numericCols: string[]) {
  const eligibility = numericCols.map((col) => ({ col, reason: vifEligibilityReason(col, rows) }));
  const usableCols = eligibility.filter((item) => !item.reason).map((item) => item.col).slice(0, 25);
  const rowsUsed = usableCols.length
    ? rows.filter((row) => usableCols.every((col) => Number.isFinite(Number(row[col])))).length
    : 0;
  return {
    rowsUsed,
    predictorsEvaluated: usableCols.length,
    predictorsExcluded: eligibility.length - usableCols.length,
    missingnessThreshold: `${Math.round(VIF_MISSINGNESS_THRESHOLD * 100)}%`,
  };
}

function previewVifRows(rows: AnyRow[], numericCols: string[]) {
  const eligibility = numericCols.map((col) => ({ col, reason: vifEligibilityReason(col, rows) }));
  const usableCols = eligibility.filter((item) => !item.reason).map((item) => item.col).slice(0, 25);
  const excludedRows = eligibility
    .filter((item) => item.reason)
    .slice(0, 8)
    .map((item) => vifResult(item.col, null, item.reason || "Non-numeric variable"));
  if (usableCols.length < 2) {
    return [
      ...usableCols.map((feature) => vifResult(feature, null, "Not enough rows")),
      ...excludedRows,
    ];
  }
  if (rows.length < usableCols.length + 2) {
    return usableCols.map((feature) => vifResult(feature, null, "Not enough rows")).concat(excludedRows);
  }
  const rowsWithVif = usableCols.map((feature) => {
    const others = usableCols.filter((col) => col !== feature);
    const clean = rows
      .map((row) => ({
        y: Number(row[feature]),
        x: others.map((col) => Number(row[col])),
      }))
      .filter((row) => Number.isFinite(row.y) && row.x.every(Number.isFinite));
    if (clean.length < others.length + 2) return vifResult(feature, null, "Not enough rows");
    const design = clean.map((row) => [1, ...row.x]);
    const xtx = design[0].map((_, c) => design[0].map((__, c2) => design.reduce((sum, row) => sum + row[c] * row[c2], 0)));
    const xty = design[0].map((_, c) => design.reduce((sum, row, i) => sum + row[c] * clean[i].y, 0));
    const beta = solveLinearSystem(xtx, xty);
    if (!beta) return vifResult(feature, null, "Singular matrix");
    const meanY = clean.reduce((sum, row) => sum + row.y, 0) / clean.length;
    const sst = clean.reduce((sum, row) => sum + (row.y - meanY) ** 2, 0);
    if (sst <= 1e-12) return vifResult(feature, null, "Constant variable");
    const sse = clean.reduce((sum, row, i) => {
      const fitted = design[i].reduce((acc, value, c) => acc + value * beta[c], 0);
      return sum + (row.y - fitted) ** 2;
    }, 0);
    const r2 = Math.max(0, Math.min(0.999999, 1 - sse / sst));
    if (1 - r2 < 1e-6) return vifResult(feature, r2, "Singular matrix");
    return vifResult(feature, r2);
  });
  return rowsWithVif.concat(excludedRows);
}

function vifResult(variable: string, r2: number | null, reason?: string) {
  const vif = r2 == null ? null : 1 / Math.max(1 - r2, 1e-9);
  const tolerance = vif == null ? null : 1 / vif;
  const status = vif == null || reason ? "Unavailable" : vif < 5 ? "Low concern" : vif < 10 ? "Moderate concern" : "High concern";
  const recommendation = vif == null
    ? reason || "Need more complete numeric modeling rows."
    : reason === "Singular matrix"
      ? "Predictor is linearly dependent on other predictors; review redundancy."
    : vif < 5
      ? "No immediate action."
      : vif < 10
        ? "Review redundant predictors before final modeling."
        : "Consider removing, combining, or regularizing correlated predictors.";
  return {
    variable,
    vif,
    tolerance,
    r2,
    status,
    reason,
    recommendation,
  };
}

// ---------------------- Component ----------------------
export default function Step05_EncodingScaling() {
  // ---- columns (from server if available) ----
  const [columns, setColumns] = useState<ColumnInfo[]>([]);
  const [targetColumn, setTargetColumn] = useState<string | null>(null);
  const [vifExcludedFeatures, setVifExcludedFeatures] = useState<string[]>(() => {
    try {
      return JSON.parse(localStorage.getItem(VIF_EXCLUDED_FEATURES_KEY) || "[]");
    } catch {
      return [];
    }
  });
  const vifExcludedSet = useMemo(() => new Set(vifExcludedFeatures), [vifExcludedFeatures]);
  const featureColumns = useMemo(() => columns.filter((column) => column.name !== targetColumn && !vifExcludedSet.has(column.name)), [columns, targetColumn, vifExcludedSet]);
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
  const [previewRowLimit, setPreviewRowLimit] = useState(10);

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
        if (rows.length) setSample(rows.slice(0, 500));
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
    () =>
      preview[0]
        ? Object.keys(preview[0]).filter((column) => column !== targetColumn)
        : [],
    [preview, targetColumn]
  );
  const displayedPreview = useMemo(() => preview.slice(0, previewRowLimit), [preview, previewRowLimit]);
  const createdFeatureRows = useMemo(() => {
    const rows: { name: string; type: string; formula: string; sources: string; leakage: string }[] = [];
    interactions.forEach((item) => rows.push({
      name: item.newName,
      type: "Interaction",
      formula: `${item.left} x ${item.right}`,
      sources: `${item.left}, ${item.right}`,
      leakage: item.left === targetColumn || item.right === targetColumn ? "Fail" : "Pass",
    }));
    bins.forEach((item) => rows.push({
      name: item.newName,
      type: "Binned numeric",
      formula: `${item.source} cut at ${item.thresholds.join(", ")}`,
      sources: item.source,
      leakage: item.source === targetColumn ? "Fail" : "Pass",
    }));
    rules.forEach((item) => rows.push({
      name: item.newName,
      type: "Rule based",
      formula: item.rules.map((rule) => `${item.source} ${rule.when.op} ${rule.when.value} => ${rule.thenLabel}`).join("; "),
      sources: item.source,
      leakage: item.source === targetColumn ? "Fail" : "Pass",
    }));
    return rows;
  }, [interactions, bins, rules, targetColumn]);
  const vifRows = useMemo(() => previewVifRows(sample, numericCols), [sample, numericCols]);
  const vifDiagnostics = useMemo(() => previewVifDiagnostics(sample, numericCols), [sample, numericCols]);

  const excludeFeatureForVif = (variable: string) => {
    setVifExcludedFeatures((current) => {
      const next = uniq([...current, variable]);
      localStorage.setItem(VIF_EXCLUDED_FEATURES_KEY, JSON.stringify(next));
      return next;
    });
  };

  const restoreFeatureFromVif = (variable: string) => {
    setVifExcludedFeatures((current) => {
      const next = current.filter((item) => item !== variable);
      localStorage.setItem(VIF_EXCLUDED_FEATURES_KEY, JSON.stringify(next));
      return next;
    });
  };

  const excludeHighVifFeatures = (threshold = VIF_AUTO_EXCLUDE_THRESHOLD) => {
    const highVifVariables = vifRows
      .filter((row) => typeof row.vif === "number" && row.vif >= threshold)
      .map((row) => row.variable);
    if (!highVifVariables.length) return;
    setVifExcludedFeatures((current) => {
      const next = uniq([...current, ...highVifVariables]);
      localStorage.setItem(VIF_EXCLUDED_FEATURES_KEY, JSON.stringify(next));
      return next;
    });
  };

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
      <section className="mb-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Feature Engineering Summary</div>
            <h3 className="mt-1 text-lg font-semibold text-slate-950">Transformation plan</h3>
            <p className="mt-1 text-sm text-slate-600">
              ATLAS excludes the target from all feature selectors and generated predictor previews to reduce leakage risk.
            </p>
          </div>
          <span className="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700">
            Target excluded: {previewCols.includes(targetColumn ?? "") ? "No" : "Yes"}
          </span>
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-5">
          <SummaryPill label="Polynomial" value={transforms.poly === "None" ? "0" : transforms.poly === "Degree 2" ? "2 preview cols" : "4 preview cols"} />
          <SummaryPill label="Interactions" value={interactions.length.toString()} />
          <SummaryPill label="Binned" value={bins.length.toString()} />
          <SummaryPill label="Rule-based" value={rules.length.toString()} />
          <SummaryPill label="Scaler" value={transforms.scaler} />
        </div>
        <div className="mt-4 overflow-hidden rounded-xl border border-slate-200">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2">Created Feature</th>
                <th className="px-3 py-2">Type</th>
                <th className="px-3 py-2">Formula / Rule</th>
                <th className="px-3 py-2">Source Variables</th>
                <th className="px-3 py-2">Leakage Check</th>
              </tr>
            </thead>
            <tbody>
              {createdFeatureRows.length ? createdFeatureRows.map((row) => (
                <tr key={row.name} className="border-t">
                  <td className="px-3 py-2 font-medium text-slate-900">{row.name}</td>
                  <td className="px-3 py-2">{row.type}</td>
                  <td className="px-3 py-2 text-slate-600">{row.formula}</td>
                  <td className="px-3 py-2">{row.sources}</td>
                  <td className={`px-3 py-2 font-semibold ${row.leakage === "Pass" ? "text-emerald-700" : "text-rose-700"}`}>{row.leakage}</td>
                </tr>
              )) : (
                <tr>
                  <td className="px-3 py-4 text-sm text-slate-500" colSpan={5}>
                    No created features yet. Add interactions, bins, or rules below to populate this audit-ready list.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
      <details className="mb-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <summary className="cursor-pointer list-none">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">VIF / Multicollinearity Analysis</div>
              <h3 className="mt-1 text-lg font-semibold text-slate-950">Predictor redundancy check</h3>
              <p className="mt-1 text-sm leading-6 text-slate-600">
                Collapsed by default. Expand to review redundant predictors and uncheck variables with high multicollinearity.
              </p>
            </div>
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-600">
              <div><span className="font-semibold text-emerald-700">VIF &lt; 5:</span> Low concern</div>
              <div><span className="font-semibold text-amber-700">5 &lt;= VIF &lt; 10:</span> Moderate concern</div>
              <div><span className="font-semibold text-rose-700">VIF &gt;= 10:</span> High concern</div>
            </div>
          </div>
        </summary>
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-blue-100 bg-blue-50 p-3">
          <div>
            <div className="text-sm font-semibold text-blue-950">Bulk redundancy action</div>
            <p className="text-xs leading-5 text-blue-900">VIF_j = 1 / (1 - R_j^2). Use VIF &gt;= {VIF_AUTO_EXCLUDE_THRESHOLD} as the high-concern threshold for automatic unchecking.</p>
          </div>
          <button
            type="button"
            className="rounded-lg bg-blue-600 px-3 py-2 text-xs font-semibold text-white shadow-sm transition hover:bg-blue-700"
            onClick={() => excludeHighVifFeatures()}
          >
            Uncheck VIF &gt;= {VIF_AUTO_EXCLUDE_THRESHOLD}
          </button>
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-4">
          <SummaryPill label="Rows used for VIF" value={vifDiagnostics.rowsUsed.toLocaleString()} />
          <SummaryPill label="Predictors evaluated" value={vifDiagnostics.predictorsEvaluated.toLocaleString()} />
          <SummaryPill label="Predictors excluded" value={(vifDiagnostics.predictorsExcluded + vifExcludedFeatures.length).toLocaleString()} />
          <SummaryPill label="Missingness threshold" value={vifDiagnostics.missingnessThreshold} />
        </div>
        {vifExcludedFeatures.length > 0 && (
          <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-3">
            <div className="text-xs font-semibold uppercase tracking-wide text-amber-800">Excluded after VIF review</div>
            <div className="mt-2 flex flex-wrap gap-2">
              {vifExcludedFeatures.map((variable) => (
                <button
                  key={variable}
                  type="button"
                  className="rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-xs font-semibold text-amber-900"
                  onClick={() => restoreFeatureFromVif(variable)}
                >
                  Restore {variable}
                </button>
              ))}
            </div>
          </div>
        )}
        <div className="mt-4 overflow-hidden rounded-xl border border-slate-200">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2">Variable</th>
                <th className="px-3 py-2 text-right">VIF</th>
                <th className="px-3 py-2 text-right">Tolerance</th>
                <th className="px-3 py-2 text-right">R-squared against other predictors</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Reason</th>
                <th className="px-3 py-2">Recommendation</th>
                <th className="px-3 py-2">Use</th>
              </tr>
            </thead>
            <tbody>
              {vifRows.length ? vifRows.map((row) => (
                <tr key={row.variable} className="border-t">
                  <td className="px-3 py-2 font-medium text-slate-900">{row.variable}</td>
                  <td className="px-3 py-2 text-right">{row.vif == null ? "-" : row.vif.toFixed(3)}</td>
                  <td className="px-3 py-2 text-right">{row.tolerance == null ? "-" : row.tolerance.toFixed(3)}</td>
                  <td className="px-3 py-2 text-right">{row.r2 == null ? "-" : row.r2.toFixed(3)}</td>
                  <td className={`px-3 py-2 font-semibold ${row.status === "Low concern" ? "text-emerald-700" : row.status === "Moderate concern" ? "text-amber-700" : row.status === "High concern" ? "text-rose-700" : "text-slate-500"}`}>{row.status}</td>
                  <td className="px-3 py-2 text-slate-600">{row.reason ?? "-"}</td>
                  <td className="px-3 py-2 text-slate-600">{row.recommendation}</td>
                  <td className="px-3 py-2">
                    <label className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs font-semibold text-slate-700">
                      <input
                        type="checkbox"
                        checked={!vifExcludedSet.has(row.variable)}
                        disabled={row.status === "Unavailable"}
                        onChange={(event) => {
                          if (event.target.checked) {
                            restoreFeatureFromVif(row.variable);
                          } else {
                            excludeFeatureForVif(row.variable);
                          }
                        }}
                      />
                      Use
                    </label>
                  </td>
                </tr>
              )) : (
                <tr>
                  <td className="px-3 py-4 text-sm text-slate-500" colSpan={8}>
                    VIF requires at least two numeric predictors and enough complete rows in the current preview sample.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </details>
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
        <p className="mb-3 text-sm leading-5 text-slate-600">
          Example: choose <span className="font-medium">merchant_category</span>, name the new feature
          <span className="font-medium"> travel_flag</span>, set default value <span className="font-medium">Other</span>,
          then define condition <span className="font-medium">CONTAINS Travel</span> with rule output value
          <span className="font-medium"> TravelRelated</span>.
        </p>
        <div className="grid gap-3 md:grid-cols-4 mb-2">
          <label className="grid gap-1 text-xs font-semibold uppercase text-slate-500">
            Feature
            <select
              className="border rounded-md px-3 py-2 text-sm font-normal normal-case text-slate-900"
              value={ruleSource}
              onChange={(e) => setRuleSource(e.target.value)}
            >
              <option value="">Select feature</option>
              {uniq([...categoricalCols, ...numericCols]).map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-xs font-semibold uppercase text-slate-500">
            New Feature Name
            <input
              className="border rounded-md px-3 py-2 text-sm font-normal normal-case text-slate-900"
              placeholder="rule_feature"
              value={ruleName}
              onChange={(e) => setRuleName(e.target.value)}
            />
          </label>
          <label className="grid gap-1 text-xs font-semibold uppercase text-slate-500">
            Default Value
            <input
              className="border rounded-md px-3 py-2 text-sm font-normal normal-case text-slate-900"
              placeholder="Other"
              value={elseLabel}
              onChange={(e) => setElseLabel(e.target.value)}
            />
          </label>
          <button
            className="self-end bg-indigo-600 hover:bg-indigo-700 text-white rounded-md px-3 py-2"
            onClick={addRuleFeature}
          >
            Add Feature
          </button>
        </div>

        {ruleRows.map((r, i) => (
          <div key={i} className="grid gap-2 md:grid-cols-6 mb-2">
            <label className="grid gap-1 text-xs font-semibold uppercase text-slate-500">
              Condition
              <select
                className="border rounded-md px-3 py-2 text-sm font-normal normal-case text-slate-900"
                value={r.op}
                onChange={(e) => updateRuleRow(i, "op", e.target.value)}
              >
                {["=", "!=", ">", ">=", "<", "<=", "IN", "NOT IN", "CONTAINS"].map(
                  (op) => (
                    <option key={op}>{op}</option>
                  )
                )}
              </select>
            </label>
            <label className="grid gap-1 text-xs font-semibold uppercase text-slate-500 md:col-span-3">
              Rule Match Value
              <input
                className="border rounded-md px-3 py-2 text-sm font-normal normal-case text-slate-900"
                placeholder="Value (comma-list for IN / NOT IN)"
                value={r.value}
                onChange={(e) => updateRuleRow(i, "value", e.target.value)}
              />
            </label>
            <label className="grid gap-1 text-xs font-semibold uppercase text-slate-500">
              Rule Output Value
              <input
                className="border rounded-md px-3 py-2 text-sm font-normal normal-case text-slate-900"
                placeholder="Then label"
                value={r.thenLabel}
                onChange={(e) => updateRuleRow(i, "thenLabel", e.target.value)}
              />
            </label>
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
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h3 className="font-semibold">Preview first {previewRowLimit} rows</h3>
          <label className="flex items-center gap-2 text-xs font-semibold uppercase text-slate-500">
            Rows
            <select
              className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm font-normal normal-case text-slate-900"
              value={previewRowLimit}
              onChange={(event) => setPreviewRowLimit(Number(event.target.value))}
            >
              {[10, 25, 50, 100].map((count) => (
                <option key={count} value={count}>{count}</option>
              ))}
            </select>
          </label>
        </div>
        <div className="overflow-auto">
          {displayedPreview.length === 0 ? (
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
                {displayedPreview.map((row, i) => (
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

function SummaryPill({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
      <div className="text-[10px] font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold text-slate-950" title={value}>{value}</div>
    </div>
  );
}
