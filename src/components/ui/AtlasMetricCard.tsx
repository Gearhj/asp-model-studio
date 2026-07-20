import type React from "react";

type AtlasMetricCardProps = {
  label: string;
  value: string | number;
  detail?: string;
  icon?: React.ReactNode;
  tone?: "neutral" | "info" | "success" | "warning" | "danger";
};

const toneClass = {
  neutral: "border-slate-200 bg-white text-slate-950",
  info: "border-blue-200 bg-blue-50 text-blue-950",
  success: "border-emerald-200 bg-emerald-50 text-emerald-950",
  warning: "border-amber-200 bg-amber-50 text-amber-950",
  danger: "border-red-200 bg-red-50 text-red-950",
};

export default function AtlasMetricCard({ label, value, detail, icon, tone = "neutral" }: AtlasMetricCardProps) {
  return (
    <div className={`rounded-lg border p-4 shadow-sm ${toneClass[tone]}`}>
      <div className="flex items-center justify-between gap-3">
        <div className="text-xs font-semibold uppercase tracking-wide opacity-75">{label}</div>
        {icon && <div className="text-current opacity-75" aria-hidden="true">{icon}</div>}
      </div>
      <div className="mt-3 truncate text-2xl font-semibold" title={String(value)}>{value}</div>
      {detail && <div className="mt-1 text-xs leading-5 opacity-75">{detail}</div>}
    </div>
  );
}
