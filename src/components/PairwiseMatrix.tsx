import React, { useMemo } from "react";

/**
 * Simple academic-looking SPLOM for top features.
 * - 2x2 grid of scatter plots (no bars)
 * - Points colored by class: Non-Fraud (0) vs Fraud (1)
 * NOTE: This is illustrative using synthetic data consistent with the rest of the UI.
 * In the backend-enabled build we’ll replace this with real sampled data.
 */

type PairwiseScatterMatrixProps = {
  title?: string;
  features: string[]; // exactly 3 or 4 numeric features preferred
};

type Point = { x: number; y: number; cls: 0 | 1 };

const frame = { top: 28, right: 16, bottom: 28, left: 36 };
const W = 320;
const H = 240;

export default function PairwiseScatterMatrix({
  title = "Pairwise Scatter Matrix (Top Features)",
  features,
}: PairwiseScatterMatrixProps) {
  // pick first 3–4 features
  const cols = features.slice(0, 4);
  const pairs = useMemo(() => {
    const out: Array<[string, string]> = [];
    for (let r = 0; r < Math.min(2, cols.length); r++) {
      for (let c = 0; c < Math.min(2, cols.length); c++) {
        if (r === c) continue;
        out.push([cols[r * 2], cols[c * 2 + 1] ?? cols[0]]);
      }
    }
    return out.slice(0, 4);
  }, [cols]);

  // synthetic points with mild correlations; 60% class 0, 40% class 1
  const data = useMemo(() => {
    const rng = (seed: number) => () => {
      seed = (seed * 1664525 + 1013904223) % 4294967296;
      return seed / 4294967296;
    };
    const rand = rng(1337);
    const make = (n: number, slope = 0.8, noise = 0.18): Point[] => {
      const pts: Point[] = [];
      for (let i = 0; i < n; i++) {
        const cls = rand() < 0.4 ? 1 : 0;
        const base = rand();
        const x = base + (cls ? 0.05 : 0) + (rand() - 0.5) * noise;
        const y = slope * base + (cls ? 0.08 : 0) + (rand() - 0.5) * noise * 1.2;
        pts.push({ x: clamp01(x), y: clamp01(y), cls: cls as 0 | 1 });
      }
      return pts;
    };
    return make(500);
  }, []);

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-6">
      <h3 className="text-sm font-semibold text-gray-700 mb-3 uppercase tracking-wide">
        {title}
      </h3>

      <div className="grid grid-cols-2 gap-6">
        {pairs.map(([fx, fy], i) => (
          <ScatterPanel key={i} fx={fx} fy={fy} data={data} />
        ))}
      </div>

      <div className="mt-3 text-[11px] text-gray-500">
        <span className="inline-block mr-4">
          <span className="inline-block w-3 h-3 rounded-full mr-1" style={{ background: "#10B981" }} />
          Non-Fraud (0)
        </span>
        <span className="inline-block mr-4">
          <span className="inline-block w-3 h-3 rounded-full mr-1" style={{ background: "#EF4444" }} />
          Fraud (1)
        </span>
        <div className="mt-1">
          <em>
            Top features are selected by absolute correlation with the target on
            the displayed sample (illustrative). In the backend run, this will be computed from the actual dataset.
          </em>
        </div>
      </div>
    </div>
  );
}

function ScatterPanel({ fx, fy, data }: { fx: string; fy: string; data: Point[] }) {
  const innerW = W - frame.left - frame.right;
  const innerH = H - frame.top - frame.bottom;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
      {/* panel bg */}
      <rect x={0} y={0} width={W} height={H} fill="#FFFFFF" stroke="#E5E7EB" />

      {/* axes */}
      <g transform={`translate(${frame.left},${frame.top})`}>
        {/* grid */}
        {[0, 0.25, 0.5, 0.75, 1].map((t, i) => (
          <g key={i}>
            <line
              x1={0}
              y1={innerH - t * innerH}
              x2={innerW}
              y2={innerH - t * innerH}
              stroke="#F3F4F6"
              strokeWidth={0.8}
            />
            <line
              x1={t * innerW}
              y1={0}
              x2={t * innerW}
              y2={innerH}
              stroke="#F3F4F6"
              strokeWidth={0.8}
            />
          </g>
        ))}

        {/* points */}
        {data.map((p, idx) => {
          const cx = p.x * innerW;
          const cy = innerH - p.y * innerH;
          const fill = p.cls ? "#EF4444" : "#10B981";
          return (
            <circle
              key={idx}
              cx={cx}
              cy={cy}
              r={1.8}
              fill={fill}
              opacity={0.55}
            />
          );
        })}

        {/* axis lines */}
        <line x1={0} y1={innerH} x2={innerW} y2={innerH} stroke="#9CA3AF" strokeWidth={1} />
        <line x1={0} y1={0} x2={0} y2={innerH} stroke="#9CA3AF" strokeWidth={1} />
      </g>

      {/* labels */}
      <text
        x={W / 2}
        y={H - 6}
        textAnchor="middle"
        fontSize={12}
        fill="#6B7280"
      >
        {fx.replaceAll("_", " ")}
      </text>
      <text
        x={14}
        y={H / 2}
        transform={`rotate(-90 14 ${H / 2})`}
        textAnchor="middle"
        fontSize={12}
        fill="#6B7280"
      >
        {fy.replaceAll("_", " ")}
      </text>
    </svg>
  );
}

function clamp01(x: number) {
  return Math.max(0, Math.min(1, x));
}
