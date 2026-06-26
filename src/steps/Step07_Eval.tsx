import React from "react";
import StepShell from "../components/StepShell";
import { useWorkflowStore } from "../state/useWorkflowStore";

export default function Step07_Eval() {
  const { markCompleteAndNext, trainResult } = useWorkflowStore();

  if (!trainResult) {
    return (
      <StepShell title="Step 8: Model Evaluation" subtitle="Train models first to see results" onNext={markCompleteAndNext}>
        <div className="rounded-lg border bg-white p-6 text-gray-600">
          No results yet. Go to <b>Model Training</b> and click <b>Train Models</b>.
        </div>
      </StepShell>
    );
  }

  const task: "binary"|"regression" = trainResult.task;

  const headers = task === "regression"
    ? ["Model","RMSE","MAE","R²","Notes"]
    : ["Model","Accuracy","Precision","Recall","F1","AUC","KS","Gini","Notes"];

  return (
    <StepShell title="Step 8: Model Evaluation" subtitle="Compare performance and analyze results" onNext={markCompleteAndNext}>
      {/* Comparison table */}
      <section className="rounded-lg border bg-white p-4 mb-6">
        <h3 className="font-semibold mb-3">Model Performance Comparison</h3>
        <div className="overflow-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-left text-gray-600">
                {headers.map((h) => <th key={h} className="pr-6 pb-2 font-medium uppercase">{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {trainResult.models.map((m: any, idx: number) => (
                <tr key={idx} className="odd:bg-gray-50">
                  <td className="pr-6 py-1 whitespace-nowrap">{m.name}{m.available ? "" : " (unavailable)"}</td>
                  {task === "regression" ? (
                    <>
                      <td className="pr-6 py-1">{fmt(m.metrics.rmse)}</td>
                      <td className="pr-6 py-1">{fmt(m.metrics.mae)}</td>
                      <td className="pr-6 py-1">{fmt(m.metrics.r2)}</td>
                      <td className="pr-6 py-1 text-xs text-gray-500">{(m.notes||[]).join(" ")}</td>
                    </>
                  ) : (
                    <>
                      <td className="pr-6 py-1">{fmt(m.metrics.accuracy)}</td>
                      <td className="pr-6 py-1">{fmt(m.metrics.precision)}</td>
                      <td className="pr-6 py-1">{fmt(m.metrics.recall)}</td>
                      <td className="pr-6 py-1">{fmt(m.metrics.f1)}</td>
                      <td className="pr-6 py-1">{fmt(m.metrics.auc)}</td>
                      <td className="pr-6 py-1">{fmt(m.metrics.ks)}</td>
                      <td className="pr-6 py-1">{fmt(m.metrics.gini)}</td>
                      <td className="pr-6 py-1 text-xs text-gray-500">{(m.notes||[]).join(" ")}</td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-4 text-sm">
          Champion: <b>{trainResult.champion ?? "N/A"}</b>
        </div>
        {trainResult.warnings?.length > 0 && (
          <div className="mt-3 text-xs text-amber-700">
            Warnings: {trainResult.warnings.join(" ")}
          </div>
        )}
      </section>

      {/* Curves (only for binary). You can wire your existing chart components if you have them. */}
      {task === "binary" && (
        <section className="grid gap-4 md:grid-cols-2">
          <div className="rounded-lg border bg-white p-4">
            <h3 className="font-semibold mb-3">ROC Curves</h3>
            <p className="text-sm text-gray-500">Curves computed on the backend; render with your chart lib of choice later.</p>
          </div>
          <div className="rounded-lg border bg-white p-4">
            <h3 className="font-semibold mb-3">Precision–Recall Curves</h3>
            <p className="text-sm text-gray-500">Data available in <code>trainResult.models[i].pr</code>.</p>
          </div>
        </section>
      )}
    </StepShell>
  );
}

function fmt(x: any) {
  if (x === undefined || x === null || Number.isNaN(x)) return "";
  if (typeof x !== "number") return String(x);
  return x.toFixed(3);
}
