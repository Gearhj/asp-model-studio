import React from "react";

type Curve = { x: number[]; y: number[] };
export default function ROCChart({
  img,
  data,
  auc,
}: {
  img?: string | null;
  data?: Curve | null;
  auc?: number | null | undefined;
}) {
  if (img) {
    return (
      <div className="bg-white border border-gray-200 rounded-lg p-4">
        <h3 className="text-sm font-semibold text-gray-700 mb-2">
          ROC Curve {typeof auc === "number" ? `(AUC = ${auc.toFixed(3)})` : ""}
        </h3>
        <img src={img} alt="ROC" className="w-full h-auto rounded" />
      </div>
    );
  }

  // Minimal fallback (should almost never be used now)
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4">
      <h3 className="text-sm font-semibold text-gray-700 mb-2">
        ROC Curve {typeof auc === "number" ? `(AUC = ${auc.toFixed(3)})` : ""}
      </h3>
      {!data ? (
        <div className="text-gray-500 text-sm">Plot unavailable.</div>
      ) : (
        <svg viewBox="0 0 400 250" className="w-full">
          <rect x="0" y="0" width="400" height="250" fill="#fff" />
          <polyline
            fill="none"
            stroke="#2563eb"
            strokeWidth="2"
            points={data.x.map((x, i) => `${x * 360 + 30},${(1 - data.y[i]) * 210 + 20}`).join(" ")}
          />
          <line x1="30" y1="230" x2="390" y2="20" stroke="#9ca3af" strokeDasharray="4 4" />
          <text x="200" y="245" textAnchor="middle" fontSize="10" fill="#6b7280">
            False Positive Rate
          </text>
          <text x="12" y="140" transform="rotate(-90 12 140)" fontSize="10" fill="#6b7280">
            True Positive Rate
          </text>
        </svg>
      )}
    </div>
  );
}
