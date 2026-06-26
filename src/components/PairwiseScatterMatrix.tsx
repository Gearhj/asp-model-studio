// src/components/PairwiseScatterMatrix.tsx
// Professional Seaborn pairplot rendered on the backend, sampled for performance.

import React, { useEffect, useMemo, useState } from "react";
import { useWorkflowStore } from "../state/useWorkflowStore";

type ImgResponse = { generated_at: string; image_base64: string | null };

const API = (import.meta as any).env?.VITE_API_BASE || "http://localhost:8000";

export default function PairwiseScatterMatrix() {
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
          rows: rows.length ? rows : null,   // backend synthesizes demo when null
          label_col: "is_fraud",
          max_numeric_for_pairs: 4,
          sample_for_pairs: 1200
        };
        const res = await fetch(`${API}/eda/pairplot`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        }).then(r => r.json());
        if (!cancelled) setImg((res as ImgResponse).image_base64);
      } catch (e: any) {
        if (!cancelled) setErr(e?.message || "Failed to render pairwise matrix.");
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
        <h3 className="text-lg font-semibold">Pairwise Scatter Matrix</h3>
        <p className="text-xs text-gray-600">Seaborn pairplot with diagonal histograms and optional label hue.</p>
      </div>
      {err && <div className="px-6 py-3 text-red-700 bg-red-50 border-b">{err}</div>}
      {loading && <div className="px-6 py-3 text-gray-700 bg-gray-50 border-b">Rendering scatter matrix…</div>}
      <div className="p-5 flex items-center justify-center">
        {img ? (
          <img src={img} alt="Pairwise Scatter Matrix" className="max-h-[720px] w-auto rounded-md border" />
        ) : (
          <div className="text-gray-500 text-sm">No image yet.</div>
        )}
      </div>
    </div>
  );
}
