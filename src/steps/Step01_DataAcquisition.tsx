// src/steps/Step01_DataAcquisition.tsx
import StepShell from "../components/StepShell";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { useNavigate } from "react-router-dom";
import { useEffect, useMemo, useRef, useState } from "react";
import { saveLocalDataset } from "../lib/localDataset";

// Safe BASE: prefer env var; fall back to local dev API; strip any trailing slash
const BASE =
  (import.meta.env?.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

/* ---------- small helpers ---------- */
function parseCSV(text: string) {
  const lines = text.replace(/\r/g, "").split("\n").filter((l) => l.trim().length);
  if (!lines.length) return { headers: [], rows: [] as Record<string, any>[] };

  // split respecting double-quotes
  const split = (line: string) => {
    const out: string[] = [];
    let cur = "";
    let inQ = false;
    for (let i = 0; i < line.length; i++) {
      const c = line[i];
      if (c === '"') inQ = !inQ;
      else if (c === "," && !inQ) {
        out.push(cur);
        cur = "";
      } else cur += c;
    }
    out.push(cur);
    return out.map((s) => s.replace(/^"(.*)"$/s, "$1"));
  };

  const headers = split(lines[0]).map((h) => h.trim());
  const rows: Record<string, any>[] = [];

  for (let i = 1; i < lines.length; i++) {
    const line = lines[i];
    if (!line || !line.trim()) continue;
    const parts = split(line);
    const r: Record<string, any> = {};
    for (let j = 0; j < headers.length; j++) {
      const k = headers[j];
      let v: any = parts[j] ?? "";
      // attempt numeric cast
      if (v !== "" && !Number.isNaN(Number(v))) {
        const n = Number(v);
        if (Number.isFinite(n)) v = n;
      }
      r[k] = v;
    }
    rows.push(r);
  }
  return { headers, rows };
}

function isNumericVector(vals: any[]) {
  let n = 0;
  let k = 0;
  for (const v of vals) {
    k++;
    if (v === null || v === undefined || v === "") continue;
    const num = Number(v);
    if (Number.isFinite(num)) n++;
  }
  return n / Math.max(1, k) >= 0.6;
}

function summarizeNumeric(vals: number[]) {
  const clean = vals.filter((v) => Number.isFinite(v));
  if (!clean.length)
    return {
      min: null,
      max: null,
      mean: null,
      median: null,
      mode: null,
      q1: null,
      q3: null,
      sd: null,
    };
  const sorted = [...clean].sort((a, b) => a - b);
  const n = sorted.length;
  const mean = sorted.reduce((acc, v) => acc + v, 0) / n;
  const quant = (p: number) => {
    const idx = (n - 1) * p;
    const lo = Math.floor(idx);
    const hi = Math.ceil(idx);
    const h = idx - lo;
    return (1 - h) * sorted[lo] + h * sorted[hi];
  };
  const median = quant(0.5);
  const q1 = quant(0.25);
  const q3 = quant(0.75);
  // mode (coarse)
  const counts = new Map<number, number>();
  for (const v of clean) counts.set(v, (counts.get(v) ?? 0) + 1);
  let mode: number | null = null;
  let best = 0;
  for (const [v, c] of counts.entries()) if (c > best) { best = c; mode = v; }
  // std deviation (unbiased)
  const variance = clean.reduce((acc, v) => acc + (v - mean) * (v - mean), 0) / (n - 1 || 1);
  const sd = Math.sqrt(variance);
  return { min: sorted[0], max: sorted[n - 1], mean, median, mode, q1, q3, sd };
}

function ivBinning(x: any[], y: (0 | 1)[], bins = 10) {
  // quick IV calc for numeric vectors using quantile bins
  const clean: Array<{ x: number; y: 0 | 1 }> = [];
  for (let i = 0; i < x.length; i++) {
    const xv = Number(x[i]);
    const yv = Number(y[i]);
    if (Number.isFinite(xv) && (yv === 0 || yv === 1)) clean.push({ x: xv, y: yv as 0 | 1 });
  }
  if (clean.length < 5) return 0;
  clean.sort((a, b) => a.x - b.x);
  const q = (p: number) => {
    const idx = (clean.length - 1) * p;
    const lo = Math.floor(idx), hi = Math.ceil(idx);
    const h = idx - lo;
    return (1 - h) * clean[lo].x + h * clean[hi].x;
  };
  const edges = [clean[0].x];
  for (let i = 1; i < bins; i++) edges.push(q(i / bins));
  edges.push(clean[clean.length - 1].x + 1e-9);

  let iv = 0;
  const nEvents = clean.filter((r) => r.y === 1).length;
  const nNone = clean.length - nEvents;
  for (let b = 0; b < edges.length - 1; b++) {
    const lo = edges[b], hi = edges[b + 1];
    let e = 0, ne = 0;
    for (const r of clean) {
      if (r.x >= lo && r.x < hi) {
        if (r.y === 1) e++; else ne++;
      }
    }
    const pe = e / Math.max(1, nEvents);
    const pne = ne / Math.max(1, nNone);
    if (pe > 0 && pne > 0) {
      iv += (pe - pne) * Math.log(pe / pne);
    }
  }
  return iv;
}

/* formatting helper: four decimals when numeric, else as-is */
function fmt4(v: any): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  return Number.isFinite(n) ? n.toFixed(4) : String(v);
}

/* ---------- component ---------- */
export default function Step01_DataAcquisition() {
  // ❗ removed s.set; we’ll use useWorkflowStore.setState for a null-safe write
  const trainSpec = useWorkflowStore((s) => (s as any)?.trainSpec);
  const navigate = useNavigate();

  const [fileName, setFileName] = useState<string>("");
  const [headers, setHeaders] = useState<string[]>([]);
  const [rows, setRows] = useState<Record<string, any>[]>([]);
  const [target, setTarget] = useState<string>("");
  const [kept, setKept] = useState<Record<string, boolean>>({});

  // file read progress
  const [isReading, setIsReading] = useState(false);
  const [readPct, setReadPct] = useState(0);
  const [saveWarning, setSaveWarning] = useState("");

  // parse upload with progress indicator
  const onFile = (f: File) => {
    const rdr = new FileReader();
    setIsReading(true);
    setReadPct(0);

    rdr.onprogress = (e) => {
      if (e.lengthComputable && e.total > 0) {
        const pct = Math.min(100, Math.round((e.loaded / e.total) * 100));
        setReadPct(pct);
      }
    };
    rdr.onload = () => {
      const { headers, rows } = parseCSV(String(rdr.result ?? ""));
      setHeaders(headers);
      setRows(rows);
      setFileName(f.name);
      const keep: Record<string, boolean> = {};
      headers.forEach((h) => (keep[h] = true));
      setKept(keep);
      if (!target) {
        // guess target if common names exist
        const guess =
          headers.find((h) => /^(fraud|label|target|class|y|bad|default|outcome|response|event)$/i.test(h)) ??
          headers.find((h) => /target/i.test(h)) ??
          "";
        setTarget(guess);
      }
      setReadPct(100);
      setTimeout(() => setIsReading(false), 250); // brief success linger
    };
    rdr.onerror = () => {
      setIsReading(false);
      alert("Failed to read file. Please confirm it is a UTF-8 CSV.");
    };
    rdr.readAsText(f);
  };

  // sample for previews (cap to 50k like server)
  const sample = useMemo(() => rows.slice(0, 50000), [rows]);

  // infer target meta
  const targetMeta = useMemo(() => {
    if (!target || !headers.includes(target)) return { kind: "none", eventRate: null } as {
      kind: "none" | "binary" | "continuous";
      eventRate: number | null;
    };
    const vals = sample.map((r) => r[target]);
    const numeric = isNumericVector(vals);
    if (!numeric) {
      // treat as categorical -> estimate event rate using minority class
      const counts = new Map<string, number>();
      for (const v of vals) counts.set(String(v), (counts.get(String(v)) ?? 0) + 1);
      const entries = Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
      const total = entries.reduce((a, [, c]) => a + c, 0);
      const nonEvent = entries[0]?.[1] ?? 0;
      const event = total - nonEvent;
      return { kind: "binary", eventRate: total ? event / total : null };
    }
    // numeric
    const ones = vals.filter((v) => Number(v) === 1).length;
    const zeros = vals.filter((v) => Number(v) === 0).length;
    const total = vals.length;
    if (ones + zeros >= total * 0.8) {
      return { kind: "binary", eventRate: total ? ones / total : null };
    }
    return { kind: "continuous", eventRate: null };
  }, [headers, sample, target]);

  // selected columns to carry forward
  const selectable = headers.filter((h) => h !== target);
  const selected = selectable.filter((h) => kept[h]);

  // push selection + target to the store (so later steps can read it)
  const persistSelection = () => {
    const prior = (trainSpec ?? {}) as any;
    const priorData = (prior?.data ?? {}) as any;

    // ✅ null-safe Zustand write without requiring a custom `set` action
    useWorkflowStore.setState((s: any) => ({
      ...s,
      hasDataset: rows.length > 0,
      trainSpec: {
        ...(s?.trainSpec ?? prior),
        data: {
          ...(s?.trainSpec?.data ?? priorData),
          source: "uploaded",
          n_samples: rows.length,
          task: targetMeta.kind === "continuous" ? "regression" : "binary",
          target,
          selected_columns: selected.length ? selected : selectable,
        },
      },
    }));
  };

  type SummRow = {
    name: string;
    type: "Numeric" | "Categorical";
    n: number;
    missing: number;
    missingPct: number;
    min: number | null;
    max: number | null;
    mean: number | null;
    median: number | null;
    mode: number | string | null;
    sd: number | null;
    iv: number | null;
  };

  // variable summary (IV for numeric vs target if binary)
  const summary: SummRow[] = useMemo(() => {
    if (!headers.length) return [];
    const out: SummRow[] = [];
    for (const h of headers) {
      const vals = sample.map((r) => r[h]);
      const numeric = isNumericVector(vals);
      const nMissing = vals.filter((v) => v === null || v === undefined || v === "").length;
      const n = sample.length;
      if (numeric) {
        const numVals = vals.map((v) => Number(v)).filter((v) => Number.isFinite(v));
        const s = summarizeNumeric(numVals);
        let iv: number | null = null;
        if (targetMeta.kind === "binary" && h !== target) {
          const y = sample.map((r) => (Number(r[target]) === 1 ? 1 : 0)) as (0 | 1)[];
          iv = ivBinning(numVals, y, 10);
        }
        out.push({
          name: h,
          type: "Numeric",
          n,
          missing: nMissing,
          missingPct: n ? (nMissing / n) * 100 : 0,
          min: s.min,
          max: s.max,
          mean: s.mean,
          median: s.median,
          mode: s.mode,
          sd: s.sd,
          iv,
        });
      } else {
        // categorical – compute mode only
        const cnt = new Map<string, number>();
        for (const v of vals) {
          const k = String(v);
          cnt.set(k, (cnt.get(k) ?? 0) + 1);
        }
        let mode: string | null = null;
        let best = 0;
        for (const [k, c] of cnt) if (c > best) { best = c; mode = k; }
        out.push({
          name: h,
          type: "Categorical",
          n,
          missing: nMissing,
          missingPct: n ? (nMissing / n) * 100 : 0,
          min: null,
          max: null,
          mean: null,
          median: null,
          mode,
          sd: null,
          iv: null,
        });
      }
    }
    // Sort: target first, then strongest IV, then name.
    return out.sort((a, b) => {
      if (a.name === target) return -1;
      if (b.name === target) return 1;
      const aIv = typeof a.iv === "number" ? a.iv : -1;
      const bIv = typeof b.iv === "number" ? b.iv : -1;
      if (aIv !== bIv) return bIv - aIv;
      return a.name.localeCompare(b.name);
    });
  }, [headers, sample, target, targetMeta]);

  const triggerNext = () => {
    const button = document.querySelector<HTMLButtonElement>("[data-step-next-button='true']");
    button?.click();
  };

  const showRareEventNote =
    targetMeta.kind === "binary" && targetMeta.eventRate !== null && targetMeta.eventRate < 0.10;

  /* ---------- UI ---------- */
  return (
    <StepShell
      title="Step 1: Data Acquisition"
      subtitle="Upload a CSV file, preview the first 10 rows, and optionally select a target variable."
      nextDisabled={!rows.length}
      onNext={async () => {
        // persist safely (no exceptions on undefined)
        persistSelection();

        // send sample + metadata to backend so later pages read the same data
        const selectable = headers.filter((h) => h !== target);
        const selectedColumns = selectable.filter((h) => kept[h]);
        const payload = {
          headers,
          // ✅ CHANGE: send full rows to backend so it has the complete dataset
          rows,  // previously: rows.slice(0, 50000)
          target: target || null,
          selected_columns: (selectedColumns.length ? selectedColumns : selectable),
        };

        const localSaveStatus = saveLocalDataset(payload);
        setSaveWarning("");
        if (localSaveStatus === "sample") {
          setSaveWarning(
            "A 5,000-row browser sample was cached for fast EDA. The full dataset will be sent to the backend in the background if it is running."
          );
        } else if (localSaveStatus === "failed") {
          setSaveWarning(
            "The browser could not cache the uploaded rows locally. EDA will still try to read the dataset from the backend."
          );
        }

        const primary = String(BASE).replace(/\/$/, "");
        const fallback = "http://127.0.0.1:8001/api";

        async function tryPost(baseUrl: string) {
          const res = await fetch(`${baseUrl}/data/set_sample`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
          const j = await res.json();
          if (!j?.ok) throw new Error(`set_sample not ok (${baseUrl})`);
          return j;
        }

        window.setTimeout(() => {
          (async () => {
            try {
              try {
                await tryPost(primary);
              } catch {
                if (primary !== fallback) {
                  await tryPost(fallback);
                  console.warn(`[DataAcquisition] VITE_API_BASE unreachable. Used fallback ${fallback}.`);
                } else {
                  throw new Error("primary failed and no fallback available");
                }
              }
            } catch (err) {
              console.error("set_sample error:", err);
            }
          })();
        }, 0);

        // hard-navigate to EDA to guarantee the next page is correct
        navigate("/step02");
      }}
    >
      {/* Upload */}
      <div className="grid grid-cols-1 gap-4">
        {saveWarning && (
          <div className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800">
            {saveWarning}
          </div>
        )}
        <div className="rounded-xl border border-gray-200 p-4">
          <div className="text-sm font-medium mb-2">Upload CSV</div>
          <div className="flex items-center gap-3">
            <label className="inline-block">
              <input
                type="file"
                accept=".csv,text/csv"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) onFile(f);
                }}
              />
              {/* @NOTE keep your exact visual affordance */}
              <span className="px-3 py-2 rounded-lg bg-blue-600 text-white text-sm cursor-pointer">
                Choose File
              </span>
            </label>
            <div className="text-sm text-gray-700">
              {fileName ? fileName : "UTF-8 CSV file; first row should contain column headers."}
            </div>
          </div>

          {/* Read progress (green bar + spinner) */}
          {isReading && (
            <div className="mt-3">
              <div className="flex items-center gap-2">
                <div className="h-4 flex-1 rounded-full bg-emerald-100 overflow-hidden">
                  <div
                    className="h-4 bg-emerald-500"
                    style={{ width: `${readPct}%`, transition: "width 200ms linear" }}
                  />
                </div>
                <div className="flex items-center gap-2 w-24">
                  <div className="w-4 h-4 rounded-full border-2 border-emerald-500 border-t-transparent animate-spin" />
                  <div className="text-xs text-emerald-700 font-medium">{readPct}%</div>
                </div>
              </div>
              <div className="text-[11px] text-gray-500 mt-1">
                Reading file into memory. Large files may take a moment.
              </div>
            </div>
          )}
        </div>

        {/* Top stats */}
        <div className="rounded-xl border p-4">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="rounded-lg border p-3">
              <div className="text-xs text-gray-500">Total Records</div>
              <div className="text-lg font-semibold">{rows.length.toLocaleString()}</div>
            </div>
            <div className="rounded-lg border p-3">
              <div className="text-xs text-gray-500">Total Features</div>
              <div className="text-lg font-semibold">{headers.length}</div>
            </div>
            <div className="rounded-lg border p-3">
              <div className="text-xs text-gray-500">Target</div>
              <div className="text-lg font-semibold">
                {target || "—"}
              </div>
            </div>
            <div className="rounded-lg border p-3">
              <div className="text-xs text-gray-500">Event Rate (sample)</div>
              <div className="text-lg font-semibold">
                {targetMeta.kind === "binary" && targetMeta.eventRate !== null
                  ? `${(targetMeta.eventRate * 100).toFixed(2)}%`
                  : "—"}
              </div>
            </div>
          </div>
          <div className="text-[11px] text-gray-400 mt-1">
            Displaying charts and preview from a sample of 50,000 rows for performance.
          </div>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-indigo-100 bg-indigo-50 px-3 py-3">
            <div>
              <div className="text-sm font-semibold text-indigo-950">Ready to continue?</div>
              <div className="text-xs text-indigo-800">Save the uploaded dataset and move to EDA when the target and kept variables look right.</div>
            </div>
            <button
              type="button"
              disabled={!rows.length}
              onClick={triggerNext}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-indigo-300"
            >
              Mark Complete & Next Step
            </button>
          </div>
        </div>

        {/* Target selection + plot + rare-event note */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="rounded-xl border p-4">
            <div className="text-sm font-medium mb-2">Target Variable</div>
            <select
              className="w-full border rounded-lg p-2"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
            >
              <option value="" disabled>
                Select target…
              </option>
              {headers.map((h) => (
                <option key={h} value={h}>
                  {h}
                </option>
              ))}
            </select>

            {/* Rare-event annotation */}
            {showRareEventNote && (
              <div className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3">
                <div className="text-xs font-semibold text-amber-800 mb-1">
                  Rare Event Detected (&lt; 10% positives)
                </div>
                <div className="text-xs text-amber-800">
                  This looks like rare-event classification. Consider rebalancing in{" "}
                  <span className="font-semibold">Balancing & Train/Test Split</span> to improve model learning.
                </div>
              </div>
            )}
          </div>

          <div className="rounded-xl border p-4">
            <div className="text-sm font-medium mb-2">Target Distribution (sample)</div>
            {target ? (
              targetMeta.kind === "binary" ? (
                <BinaryBar values={sample.map((r) => r[target])} />
              ) : (
                <Histogram values={sample.map((r) => Number(r[target]))} />
              )
            ) : (
              <div className="text-sm text-gray-500">Select a target to view its distribution.</div>
            )}
          </div>
        </div>

        {/* Variable Summary + IV + Keep toggles */}
        {summary.length > 0 && (
          <div className="rounded-xl border p-4">
            <div className="flex items-center justify-between">
              <div className="text-sm font-medium">Variable Summary (sample)</div>
              <div className="text-xs space-x-3">
                <button
                  className="text-indigo-600 hover:underline"
                  onClick={() => {
                    const all: Record<string, boolean> = {};
                    headers.forEach((h) => (all[h] = h !== target));
                    setKept(all);
                  }}
                >
                  Select all
                </button>
                <button
                  className="text-gray-600 hover:underline"
                  onClick={() => {
                    const none: Record<string, boolean> = {};
                    headers.forEach((h) => (none[h] = false));
                    setKept(none);
                  }}
                >
                  None
                </button>
              </div>
            </div>
            <div className="mt-2 text-xs text-gray-500">
              Showing the strongest variables first. The table viewport displays about 20 rows at a time; scroll inside the table for the remaining features.
            </div>

            <div className="overflow-auto mt-3 max-h-[760px] rounded-lg border border-gray-100">
              <table className="min-w-full text-sm">
                <thead className="sticky top-0 z-10 bg-white">
                  <tr className="text-gray-600 shadow-sm">
                    <th className="py-2 px-3 text-center">Keep</th>
                    <th className="py-2 px-3 text-left">Variable</th>
                    <th className="py-2 px-3 text-center">IV</th>
                    <th className="py-2 px-3 text-center">Type</th>
                    <th className="py-2 px-3 text-center">N</th>
                    <th className="py-2 px-3 text-center">Missing %</th>
                    <th className="py-2 px-3 text-center">Std Dev</th>
                    <th className="py-2 px-3 text-center">Min</th>
                    <th className="py-2 px-3 text-center">Max</th>
                    <th className="py-2 px-3 text-center">Mean</th>
                    <th className="py-2 px-3 text-center">Median</th>
                    <th className="py-2 px-3 text-center">Mode</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.map((s) => {
                    const ivHi = typeof s.iv === "number" && s.iv > 0.01;
                    return (
                      <tr key={s.name} className="border-t border-gray-100">
                        <td className="py-2 px-3 text-center">
                          {s.name === target ? (
                            <span className="text-[11px] text-gray-400">target</span>
                          ) : (
                            <input
                              type="checkbox"
                              checked={!!kept[s.name]}
                              onChange={(e) =>
                                setKept((prev) => ({ ...prev, [s.name]: e.target.checked }))
                              }
                            />
                          )}
                        </td>
                        <td className="py-2 px-3 text-left font-medium text-gray-800">{s.name}</td>
                        <td
                          className={
                            "py-2 px-3 text-center " +
                            (ivHi ? "bg-emerald-50 text-emerald-700 font-semibold rounded" : "")
                          }
                        >
                          {s.iv === null ? "—" : s.iv.toFixed(4)}
                        </td>
                        <td className="py-2 px-3 text-center">{s.type}</td>
                        <td className="py-2 px-3 text-center">{s.n.toLocaleString()}</td>
                        <td className="py-2 px-3 text-center">{s.missingPct.toFixed(2)}%</td>
                        <td className="py-2 px-3 text-center">{fmt4(s.sd)}</td>
                        <td className="py-2 px-3 text-center">{fmt4(s.min)}</td>
                        <td className="py-2 px-3 text-center">{fmt4(s.max)}</td>
                        <td className="py-2 px-3 text-center">{fmt4(s.mean)}</td>
                        <td className="py-2 px-3 text-center">{fmt4(s.median)}</td>
                        <td className="py-2 px-3 text-center">{fmt4(s.mode)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </StepShell>
  );
}

/* ---------- lightweight charts (no extra libs) ---------- */

function BinaryBar({ values, height = 200 }: { values: any[]; height?: number }) {
  const n = values.length;
  const c0 = values.filter((v) => String(v) === "0" || String(v).toLowerCase() === "false").length;
  const c1 = values.filter((v) => String(v) === "1" || String(v).toLowerCase() === "true").length;
  // if labels aren’t 0/1/true/false, treat minority as event
  let leftLabel = "Non-Event", rightLabel = "Event";
  let left = c0, right = c1;
  if (c0 === 0 && c1 === 0) {
    const counts = new Map<string, number>();
    for (const v of values) counts.set(String(v), (counts.get(String(v)) ?? 0) + 1);
    const entries = Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
    leftLabel = entries[0][0];
    rightLabel = entries[1]?.[0] ?? "Other";
    left = entries[0][1];
    right = entries[1]?.[1] ?? 0;
  }
  const max = Math.max(left, right, 1);
  const w = 380;
  const pad = 40;

  return (
    <svg width={420} height={height}>
      <line x1={pad} y1={height - 22} x2={pad + w} y2={height - 22} stroke="#ddd" />
      <rect x={pad + 40} y={height - 22 - (left / max) * (height - 60)} width={80} height={(left / max) * (height - 60)} fill="#9CA3AF" />
      <rect x={pad + 160} y={height - 22 - (right / max) * (height - 60)} width={80} height={(right / max) * (height - 60)} fill="#10B981" />
      <text x={pad + 80} y={height - 6} textAnchor="middle" fontSize="10" fill="#374151">{leftLabel}</text>
      <text x={pad + 200} y={height - 6} textAnchor="middle" fontSize="10" fill="#374151">{rightLabel}</text>
      <text x={pad + 80} y={height - 30 - (left / max) * (height - 60)} textAnchor="middle" fontSize="10" fill="#111827">{left.toLocaleString()}</text>
      <text x={pad + 200} y={height - 30 - (right / max) * (height - 60)} textAnchor="middle" fontSize="10" fill="#111827">{right.toLocaleString()}</text>
    </svg>
  );
}

function Histogram({ values, height = 200 }: { values: number[]; height?: number }) {
  const clean = values.filter((v) => Number.isFinite(v));
  if (!clean.length) return <div className="text-xs text-gray-500">No data</div>;
  const sorted = [...clean].sort((a, b) => a - b);
  const n = sorted.length;
  const nb = Math.min(32, Math.max(8, Math.round(Math.sqrt(n))));
  const min = sorted[0], max = sorted[n - 1];
  const w = max - min || 1;
  const bins = new Array(nb).fill(0);
  for (const v of sorted) {
    const idx = Math.min(nb - 1, Math.floor(((v - min) / w) * nb));
    bins[idx] += 1;
  }
  const H = height;
  const W = 420;
  const pad = 40;
  const barW = (W - pad - 10) / nb;
  const maxN = Math.max(...bins, 1);

  return (
    <svg width={W} height={H}>
      <line x1={pad} y1={H - 22} x2={W - 10} y2={H - 22} stroke="#ddd" />
      {bins.map((n, i) => {
        const x = pad + i * barW + 1;
        const h = ((n / maxN) * (H - 60)) | 0;
        return <rect key={i} x={x} y={H - 22 - h} width={barW - 2} height={h} fill="#9CA3AF" />;
      })}
    </svg>
  );
}

function TopKBar({ values, height = 200 }: { values: string[]; height?: number }) {
  const counts = new Map<string, number>();
  for (const v of values) counts.set(v, (counts.get(v) ?? 0) + 1);
  const top = Array.from(counts.entries()).sort((a, b) => b[1] - a[1]).slice(0, 8);
  if (!top.length) return <div className="text-xs text-gray-500">No data</div>;
  const total = values.length;
  const max = Math.max(...top.map(([, c]) => c), 1);
  const W = 420, H = height, pad = 60;

  return (
    <svg width={W} height={H}>
      <line x1={pad} y1={H - 20} x2={W - 10} y2={H - 20} stroke="#ddd" />
      {top.map(([k, c], i) => {
        const w = (c / total) * (W - pad - 20);
        const y = 20 + i * 20;
        return (
          <g key={k}>
            <rect x={pad} y={y - 10} width={w} height={14} fill="#9CA3AF" />
            <text x={pad - 6} y={y} textAnchor="end" fontSize="10" fill="#374151">{k}</text>
            <g>
              <text x={pad + w + 4} y={y} fontSize="10" fill="#111827">
                {c.toLocaleString()}
              </text>
            </g>
          </g>
        );
      })}
    </svg>
  );
}
