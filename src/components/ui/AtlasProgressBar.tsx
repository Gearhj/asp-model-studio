type AtlasProgressBarProps = {
  value: number;
  label?: string;
  className?: string;
};

export default function AtlasProgressBar({ value, label, className = "" }: AtlasProgressBarProps) {
  const safeValue = Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0));
  return (
    <div className={className}>
      {label && (
        <div className="mb-2 flex items-center justify-between gap-3 text-xs font-semibold text-slate-600">
          <span>{label}</span>
          <span>{safeValue}%</span>
        </div>
      )}
      <div className="h-2 overflow-hidden rounded-full bg-slate-200" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={safeValue}>
        <div className="h-full rounded-full bg-blue-600" style={{ width: `${safeValue}%` }} />
      </div>
    </div>
  );
}
