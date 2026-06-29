import React, { useEffect, useMemo, useState } from "react";

const BASE: string =
  (typeof window !== "undefined" && (window as any).API_BASE) ||
  (import.meta as any)?.env?.VITE_API_BASE ||
  "http://127.0.0.1:8001/api";

type SampleResponse = {
  ok?: boolean;
  headers?: string[];
  rows?: Array<Record<string, unknown>>;
};

function numericSeries(rows: Array<Record<string, unknown>>, feature: string) {
  return rows
    .map((row) => Number(row[feature]))
    .filter((value) => Number.isFinite(value));
}

function variance(values: number[]) {
  if (values.length < 2) return 0;
  const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
  return values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / (values.length - 1);
}

export default function D3Pairplot({ samplePct = 10 }: { samplePct?: number }) {
  const [rows, setRows] = useState<Array<Record<string, unknown>>>([]);
  const [headers, setHeaders] = useState<string[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let abort = false;
    (async () => {
      try {
        setError("");
        const r = await fetch(`${BASE}/eda/sample?max_rows=2500`);
        const j = (await r.json()) as SampleResponse;
        if (abort) return;
        if (!j?.rows?.length || !j?.headers?.length) {
          setError("Pairwise plots unavailable until a dataset is loaded.");
          return;
        }
        const pct = Math.max(1, Math.min(100, samplePct || 10));
        const count = Math.max(50, Math.ceil(j.rows.length * (pct / 100)));
        setRows(j.rows.slice(0, count));
        setHeaders(j.headers);
      } catch (err: any) {
        if (!abort) setError(err?.message || "Pairwise plots unavailable.");
      }
    })();
    return () => {
      abort = true;
    };
  }, [samplePct]);

  const features = useMemo(() => {
    return headers
      .map((feature) => {
        const values = numericSeries(rows, feature);
        return { feature, values, variance: variance(values) };
      })
      .filter((item) => item.values.length >= 10)
      .sort((a, b) => b.variance - a.variance)
      .slice(0, 4)
      .map((item) => item.feature);
  }, [headers, rows]);

  if (error) return <div className="text-sm text-gray-500">{error}</div>;
  if (features.length < 2) {
    return <div className="text-sm text-gray-500">Pairwise plots unavailable (need at least two numeric columns).</div>;
  }

  return <PairwiseSvg rows={rows} features={features} />;
}

export function PairwiseSvg({ rows, features }: { rows: Array<Record<string, unknown>>; features: string[] }) {
  const cell = 150;
  const pad = 30;
  const gap = 10;
  const size = features.length * cell + (features.length - 1) * gap + pad;
  const domains = useMemo(() => {
    const result: Record<string, [number, number]> = {};
    features.forEach((feature) => {
      const values = numericSeries(rows, feature);
      const min = Math.min(...values);
      const max = Math.max(...values);
      result[feature] = min === max ? [min - 1, max + 1] : [min, max];
    });
    return result;
  }, [features, rows]);

  const scale = (value: number, domain: [number, number], start: number, end: number) =>
    start + ((value - domain[0]) / (domain[1] - domain[0] || 1)) * (end - start);

  return (
    <div className="flex min-h-[620px] items-center justify-center overflow-auto rounded-xl bg-slate-50 p-4">
      <svg viewBox={`0 0 ${size} ${size}`} className="h-auto max-h-[660px] w-full min-w-[560px] max-w-[780px] rounded-xl bg-slate-50">
        {features.map((yFeature, rowIndex) =>
          features.map((xFeature, colIndex) => {
            const x0 = pad + colIndex * (cell + gap);
            const y0 = rowIndex * (cell + gap);
            const xDomain = domains[xFeature];
            const yDomain = domains[yFeature];
            const points = rows
              .map((row) => ({ x: Number(row[xFeature]), y: Number(row[yFeature]) }))
              .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y))
              .slice(0, 900);
            return (
              <g key={`${xFeature}-${yFeature}`} transform={`translate(${x0},${y0})`}>
                <rect x={0} y={0} width={cell} height={cell} rx={8} fill="white" stroke="#e2e8f0" />
                {xFeature === yFeature ? (
                  <HistogramCell values={points.map((point) => point.x)} width={cell} height={cell} />
                ) : (
                  points.map((point, index) => (
                    <circle
                      key={index}
                      cx={scale(point.x, xDomain, 12, cell - 12)}
                      cy={scale(point.y, yDomain, cell - 12, 12)}
                      r={2}
                      fill="#2563eb"
                      opacity={0.38}
                    />
                  ))
                )}
                {rowIndex === features.length - 1 && (
                  <text x={cell / 2} y={cell + 14} textAnchor="middle" className="fill-slate-600 text-[10px]">
                    {xFeature}
                  </text>
                )}
                {colIndex === 0 && (
                  <text x={-10} y={cell / 2} textAnchor="middle" transform={`rotate(-90 -10 ${cell / 2})`} className="fill-slate-600 text-[10px]">
                    {yFeature}
                  </text>
                )}
              </g>
            );
          })
        )}
      </svg>
    </div>
  );
}

function HistogramCell({ values, width, height }: { values: number[]; width: number; height: number }) {
  if (!values.length) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const bins = Array.from({ length: 12 }, () => 0);
  values.forEach((value) => {
    const index = Math.min(bins.length - 1, Math.floor(((value - min) / (max - min || 1)) * bins.length));
    bins[index] += 1;
  });
  const maxCount = Math.max(...bins, 1);
  const barWidth = (width - 24) / bins.length;
  return (
    <>
      {bins.map((count, index) => {
        const barHeight = ((height - 32) * count) / maxCount;
        return (
          <rect
            key={index}
            x={12 + index * barWidth}
            y={height - 14 - barHeight}
            width={Math.max(2, barWidth - 2)}
            height={barHeight}
            rx={2}
            fill="#64748b"
            opacity={0.72}
          />
        );
      })}
    </>
  );
}
