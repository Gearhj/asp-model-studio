import React from "react";

type Curve = { x: number[]; y: number[] };
export default function PRChart({
  img,
  data,
}: {
  img?: string | null;
  data?: Curve | null;
}) {
  if (img) {
    return (
      <div className="bg-white border border-gray-200 rounded-lg p-4">
        <h3 className="text-sm font-semibold text-gray-700 mb-2">Precision–Recall Curve</h3>
        <img src={img} alt="PR" className="w-full h-auto rounded" />
      </div>
    );
  }

  // fallback
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4">
      <h3 className="text-sm font-semibold text-gray-700 mb-2">Precision–Recall Curve</h3>
      {!data ? (
        <div className="text-gray-500 text-sm">Plot unavailable.</div>
      ) : (
        <svg viewBox="0 0 400 250" className="w-full">
          <rect x="0" y="0" width="400" height="250" fill="#fff" />
          <polyline
            fill="none"
            stroke="#7c3aed"
            strokeWidth="2"
            points={data.x.map((x, i) => `${x * 360 + 30},${(1 - data.y[i]) * 210 + 20}`).join(" ")}
          />
          <text x="200" y="245" textAnchor="middle" fontSize="10" fill="#6b7280">
            Recall
          </text>
          <text x="12" y="140" transform="rotate(-90 12 140)" fontSize="10" fill="#6b7280">
            Precision
          </text>
        </svg>
      )}
    </div>
  );
}
