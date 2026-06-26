// src/components/D3Boxplot.tsx
import { useEffect, useMemo, useState } from "react";

type Props = {
  feature: string;
  samplePct?: number; // 0.5–100 (server enforces)
  height?: number;
  // kept for backward compatibility; not used by the endpoint
  datasetId?: string;
};

const BASE =
  (import.meta as any)?.env?.VITE_API_BASE?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

export default function D3Boxplot({
  feature,
  samplePct = 10,
  height = 260,
}: Props) {
  const [dataUrl, setDataUrl] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Build the request URL once per feature / samplePct change
  const queryUrl = useMemo(() => {
    const params = new URLSearchParams({
      feature: feature || "",
      sample_pct: String(samplePct),
    });
    return `${BASE}/eda/boxplot?${params.toString()}`;
  }, [feature, samplePct]);

  useEffect(() => {
    let alive = true;

    async function fetchBox() {
      if (!feature) {
        // no feature selected → clear panel
        if (!alive) return;
        setDataUrl("");
        setErr(null);
        return;
      }

      if (!alive) return;

      setLoading(true);
      setErr(null);
      setDataUrl("");

      try {
        const r = await fetch(queryUrl);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);

        const j = await r.json();
        if (!j?.ok || !j?.image_b64) {
          throw new Error("Invalid payload from /api/eda/boxplot");
        }

        if (!alive) return;
        setDataUrl(`data:image/png;base64,${j.image_b64}`);
      } catch (e: any) {
        if (!alive) return;
        setDataUrl("");
        setErr(e?.message || "Unable to render box-plot.");
      } finally {
        if (!alive) return;
        setLoading(false);
      }
    }

    fetchBox();

    return () => {
      // mark this effect as obsolete so we don't set state after unmount
      alive = false;
    };
  }, [feature, samplePct, queryUrl]);

  if (!feature) {
    return (
      <div className="text-xs text-gray-500">
        Select a dataset and feature to render the Box-Plot.
      </div>
    );
  }

  return (
    <div className="w-full">
      {loading && (
        <div className="text-xs text-gray-500">Rendering box-plot…</div>
      )}
      {!loading && dataUrl && (
        <img
          src={dataUrl}
          alt={`Box plot — ${feature}`}
          style={{ height, width: "100%", objectFit: "contain" }}
        />
      )}
      {!loading && !dataUrl && err && (
        <div className="text-xs text-red-600">
          Unable to render Box-Plot. {err}. Verify the backend endpoint{" "}
          <code className="ml-1">/api/eda/boxplot</code> is reachable.
        </div>
      )}
    </div>
  );
}
