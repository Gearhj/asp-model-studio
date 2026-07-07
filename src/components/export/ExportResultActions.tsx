import type { AnalyticsExportFormat } from "../../lib/analyticsWorkbench";

type ExportResultActionsProps = {
  resultType: string;
  label?: string;
  payload: Record<string, unknown>;
  formats?: Array<"excel">;
  onExport: (format: AnalyticsExportFormat, resultType: string, payload: Record<string, unknown>) => void;
};

export default function ExportResultActions({ resultType, label = "Export to Excel", payload, formats = ["excel"], onExport }: ExportResultActionsProps) {
  if (!formats.includes("excel")) return null;
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      <button
        type="button"
        onClick={() => onExport("excel", resultType, payload)}
        className="rounded-lg border border-emerald-200 bg-white px-3 py-2 text-sm font-semibold text-emerald-800 shadow-sm hover:border-emerald-400 hover:bg-emerald-50"
      >
        {label}
      </button>
    </div>
  );
}
