// src/lib/d3Utils.ts
export function toNumber(v: any, fallback = 0) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

export function toBool(v: any, fallback = false) {
  if (v === true || v === false) return v;
  const s = String(v).toLowerCase();
  if (s === "1" || s === "true" || s === "yes") return true;
  if (s === "0" || s === "false" || s === "no") return false;
  return fallback;
}

export function sampleArray<T>(arr: T[], pct = 0.1, max = 50000): T[] {
  const n = Math.min(max, Math.ceil(arr.length * Math.max(0, Math.min(1, pct))));
  if (n >= arr.length) return arr.slice();
  const out: T[] = [];
  const step = arr.length / n;
  for (let i = 0; i < arr.length; i += step) {
    out.push(arr[Math.floor(i)]);
  }
  return out;
}
