import type { ReactNode } from "react";

export function AnalyticalResultCard({ title, children, tone = "blue" }: { title: string; children: ReactNode; tone?: "blue" | "emerald" | "slate" }) {
  const palette = tone === "emerald" ? "border-emerald-200 bg-emerald-50/60" : tone === "slate" ? "border-slate-200 bg-white" : "border-blue-200 bg-blue-50/60";
  return <section className={`rounded-xl border p-4 shadow-sm ${palette}`}><h3 className="text-sm font-semibold text-slate-950">{title}</h3><div className="mt-3">{children}</div></section>;
}
