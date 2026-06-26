// src/components/CorrelationHeatmap.tsx
// Professional annotated heatmap rendered on the backend with Seaborn.

import React, { useEffect, useMemo, useState } from "react";
import { useWorkflowStore } from "../state/useWorkflowStore";

type ImgResponse = { generated_at: string; image_base64: string | null };

const API = (import.meta as any).env?.VITE_API_BASE || "http://localhost:8000";

export default function CorrelationHeatmap() {
  const data = useWorkflowStore((s: any) => s.data || s.dataset || s.table || null);

  const rows = useMemo<any[]>(() => {
    if (!data) return [];
    if (Array.isArray(data)) return data;
    if (Array.isArray(data?.rows)) return data.rows;
    return [];
  }, [data]);

  const [img, setImg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(false);

  useEffect(() => {
    let cancelled = false;
    async function run() {
      setLoading(true);
      setErr(null);
      try {
        const payload = {
          rows: rows.length ? rows : null,      // backend will synthesize demo if null
          max_numeric_for_corr: 10
        };
        const res = await fetch(`${API}/eda/corr_heatmap`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        }).then(r => r.json());
        if (!cancelled) setImg((res as ImgResponse).image_base64);
      } catch (e: any) {
        if (!cancelled) setErr(e?.message || "Failed to render heatmap.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    run();
    return () => { cancelled = true; };
  }, [rows]);

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-0">
      <div className="px-6 pt-5 pb-3 border-b">
        <h3 className="text-lg font-semibold">Correlation Heatmap</h3>
        <p className="text-xs text-gray-600">Pearson correlation with annotated lower triangle and academic styling.</p>
      </div>
      {err && <div className="px-6 py-3 text-red-700 bg-red-50 border-b">{err}</div>}
      {loading && <div className="px-6 py-3 text-gray-700 bg-gray-50 border-b">Rendering heatmap…</div>}
      <div className="p-5 flex items-center justify-center">
        {img ? (
          <img src={img} alt="Correlation Heatmap" className="max-h-[560px] w-auto rounded-md border" />
        ) : (
          <div className="text-gray-500 text-sm">No image yet.</div>
        )}
      </div>
    </div>
  );
}
