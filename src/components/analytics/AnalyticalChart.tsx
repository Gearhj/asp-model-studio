import type { AnalyticalChart as Chart } from "../../types/analyticsEngine";

export function AnalyticalChart({ chart }: { chart: Chart }) {
  const y = chart.y_axes[0]?.field;
  const points = chart.data.map((row, index) => ({ x: Number(row[chart.x_axis.field] ?? index), y: Number(row[y] ?? 0) })).filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y));
  if (!points.length) return <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-5 text-sm text-slate-500">Chart-ready data is unavailable for this result.</div>;
  const minX=Math.min(...points.map((point)=>point.x)),maxX=Math.max(...points.map((point)=>point.x)),minY=Math.min(...points.map((point)=>point.y)),maxY=Math.max(...points.map((point)=>point.y)); const sx=(value:number)=>40+(value-minX)/Math.max(maxX-minX,1)*540; const sy=(value:number)=>180-(value-minY)/Math.max(maxY-minY,1)*145;
  return <figure className="rounded-lg border border-slate-200 bg-white p-3"><figcaption className="mb-2 text-sm font-semibold text-slate-900">{chart.title}</figcaption><svg viewBox="0 0 610 215" className="h-56 w-full"><line x1="40" x2="580" y1="180" y2="180" stroke="#94a3b8"/><line x1="40" x2="40" y1="20" y2="180" stroke="#94a3b8"/>{chart.chart_type === "bar" || chart.chart_type === "histogram" ? points.map((point,index)=><rect key={index} x={sx(point.x)-6} y={sy(point.y)} width="12" height={180-sy(point.y)} fill="#2563eb"/>):<polyline points={points.map((point)=>`${sx(point.x)},${sy(point.y)}`).join(" ")} fill="none" stroke="#0f766e" strokeWidth="3"/>}<text x="310" y="208" textAnchor="middle" fontSize="10" fill="#475569">{chart.x_axis.label}</text></svg></figure>;
}
