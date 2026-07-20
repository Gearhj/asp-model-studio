type AtlasStatusBadgeProps = {
  children: string;
  tone?: "neutral" | "info" | "success" | "warning" | "danger";
  className?: string;
};

const toneClass = {
  neutral: "bg-slate-100 text-slate-700 ring-slate-200",
  info: "bg-blue-100 text-blue-800 ring-blue-200",
  success: "bg-emerald-100 text-emerald-800 ring-emerald-200",
  warning: "bg-amber-100 text-amber-800 ring-amber-200",
  danger: "bg-red-100 text-red-800 ring-red-200",
};

export default function AtlasStatusBadge({ children, tone = "neutral", className = "" }: AtlasStatusBadgeProps) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ${toneClass[tone]} ${className}`}>
      {children}
    </span>
  );
}
