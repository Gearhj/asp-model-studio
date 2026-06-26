import React, { useMemo } from "react";

export default function DecileLiftTable({
  yTrue,
  yScore,
}: {
  yTrue?: number[];
  yScore?: number[];
}) {
  // guard
  if (!yTrue || !yScore || yTrue.length !== yScore.length) {
    return (
      <div className="bg-white border border-gray-200 rounded-lg p-4">
        <h3 className="text-sm font-semibold text-gray-700 mb-2">Decile Lift (Champion Model)</h3>
        <p className="text-sm text-gray-500">Scores/labels not available for decile analysis.</p>
      </div>
    );
  }

  const rows = useMemo(() => {
    const N = yTrue.length;
    const idx = Array.from({ length: N }, (_, i) => i).sort((a, b) => yScore[b] - yScore[a]);
    const sortedY = idx.map((i) => yTrue[i]);
    const totalPos = sortedY.reduce((s, v) => s + (v ? 1 : 0), 0);
    const baseRate = totalPos / N;

    const size = Math.floor(N / 10);
    const out: {
      decile: number;
      n: number;
      positives: number;
      respRate: number;
      lift: number;
      cumCapture: number;
    }[] = [];

    let cumPos = 0;
    for (let d = 0; d < 10; d++) {
      const start = d * size;
      const end = d === 9 ? N : (d + 1) * size;
      const slice = sortedY.slice(start, end);
      const n = slice.length;
      const pos = slice.reduce((s, v) => s + (v ? 1 : 0), 0);
      cumPos += pos;
      const resp = n ? pos / n : 0;
      const lift = baseRate > 0 ? resp / baseRate : 0;
      const cum = totalPos > 0 ? cumPos / totalPos : 0;
      out.push({
        decile: d + 1,
        n,
        positives: pos,
        respRate: resp,
        lift,
        cumCapture: cum,
      });
    }
    return { rows: out, baseRate, totalPos, N };
  }, [yTrue, yScore]);

  const fmtPct = (p: number) => `${(p * 100).toFixed(2)}%`;
  const fmtX = (x: number) => `${x.toFixed(2)}x`;

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4">
      <h3 className="text-sm font-semibold text-gray-700 mb-2">Decile Lift (Champion Model)</h3>
      <p className="text-xs text-gray-500 mb-3">
        Base rate: {fmtPct(rows.baseRate)} · Total samples: {rows.N.toLocaleString()} · Positives:{" "}
        {rows.totalPos.toLocaleString()}
      </p>
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="text-gray-600 border-b">
              <th className="py-2 px-2 text-left">Decile</th>
              <th className="py-2 px-2 text-center">N</th>
              <th className="py-2 px-2 text-center">Positives</th>
              <th className="py-2 px-2 text-center">Response Rate</th>
              <th className="py-2 px-2 text-center">Lift</th>
              <th className="py-2 px-2 text-center">Cumulative Capture</th>
            </tr>
          </thead>
          <tbody>
            {rows.rows.map((r) => (
              <tr key={r.decile} className="border-b last:border-0">
                <td className="py-2 px-2">{r.decile}</td>
                <td className="py-2 px-2 text-center">{r.n.toLocaleString()}</td>
                <td className="py-2 px-2 text-center">{r.positives.toLocaleString()}</td>
                <td className="py-2 px-2 text-center">{fmtPct(r.respRate)}</td>
                <td className="py-2 px-2 text-center">{fmtX(r.lift)}</td>
                <td className="py-2 px-2 text-center">{fmtPct(r.cumCapture)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
