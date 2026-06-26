// src/components/D3Heatmap.tsx
import React, { useEffect, useState } from "react";

const BASE: string =
  (typeof window !== "undefined" && (window as any).API_BASE) ||
  (import.meta as any)?.env?.VITE_API_BASE ||
  "/api";

export default function D3Heatmap({ samplePct = 10, limit = 20 }: { samplePct?: number; limit?: number }) {
  const [b64, setB64] = useState<string | null>(null);

  useEffect(() => {
    let abort = false;
    (async () => {
      try {
        const cappedLimit = Math.max(2, Math.min(20, limit));
        const r = await fetch(`${BASE}/eda/corr?sample_pct=${samplePct}&limit=${cappedLimit}`);
        const j = await r.json();
        if (abort) return;
        setB64(j?.ok && j?.image_b64 ? `data:image/png;base64,${j.image_b64}` : null);
      } catch {
        if (!abort) setB64(null);
      }
    })();
    return () => {
      abort = true;
    };
  }, [samplePct, limit]);

  if (!b64) {
    return <div className="text-sm text-gray-500">Not enough numeric columns to compute correlations.</div>;
  }
  return <img alt="corr" src={b64} className="max-w-full" />;
}
