import { useState } from "react";
import { Share2 } from "lucide-react";
import ShareResourceDialog from "./ShareResourceDialog";

export type ResultShareAction = {
  label: string;
  resourceType: string;
  resourceId?: string;
  resourceName?: string;
};

export const supportedResultShareActions: ResultShareAction[] = [
  { label: "Share Optimization Solution", resourceType: "optimization_solution" },
  { label: "Share Allocation CSV/export", resourceType: "export_artifact" },
  { label: "Share Sensitivity Results", resourceType: "evidence_artifact" },
  { label: "Share Validation Result", resourceType: "validation_result" },
  { label: "Share Model Run", resourceType: "model_run_result" },
  { label: "Share Model Comparison", resourceType: "run_record" },
  { label: "Share Evaluation Results", resourceType: "evaluation_report" },
  { label: "Share Scored Dataset", resourceType: "scored_dataset" },
  { label: "Share Forecast Result", resourceType: "forecast_result" },
  { label: "Share Backtest Results", resourceType: "evaluation_report" },
  { label: "Share Forecast CSV/export", resourceType: "export_artifact" },
  { label: "Share Prompt Package", resourceType: "documentation_package" },
  { label: "Share Source Inventory", resourceType: "evidence_artifact" },
  { label: "Share Safety Review", resourceType: "validation_result" },
  { label: "Share Documentation Package", resourceType: "documentation_package" },
];

export default function ResultShareActions({ actions }: { actions: ResultShareAction[] }) {
  const visible = actions.filter((action) => action.resourceId);
  const [selected, setSelected] = useState<ResultShareAction | null>(null);
  if (!visible.length) return null;
  return (
    <div className="flex flex-wrap gap-2" data-testid="result-share-actions">
      {visible.map((action) => (
        <button key={`${action.resourceType}-${action.resourceId}-${action.label}`} type="button" className="atlas-secondary-button" onClick={() => setSelected(action)}>
          <Share2 size={15} /> {action.label}
        </button>
      ))}
      {selected && (
        <ShareResourceDialog
          open
          onClose={() => setSelected(null)}
          resourceType={selected.resourceType}
          resourceId={selected.resourceId || ""}
          resourceName={selected.resourceName || selected.label}
        />
      )}
    </div>
  );
}
