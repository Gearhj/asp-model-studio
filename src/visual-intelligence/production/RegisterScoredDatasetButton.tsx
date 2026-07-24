// ATLAS Visual Intelligence Production Integration, Phase K -- "Register Scored
// Dataset" action, callable from a production panel for a scoring-session
// analysis. Registers a BOUNDED extract of the ScoringRun's governed output
// (never the full enterprise-scale artifact through the browser -- see
// Do-Not #4) and cross-links both sides (ScoringRun.outputDatasetId <->
// DatasetVersion.sourceInfo.sourceScoringRunId) via the scoringRunId field
// added to /api/scoring/register-scored-dataset.
import { useState } from "react";
import { getScoringRun, getScoringRunRows } from "../../scoring-runs/scoringRunClient";
import { registerScoredDataset } from "../../lib/modelDiagnostics";
import type { VisualAnalysisContext } from "./visualAnalysisContext";

const REGISTRATION_ROW_LIMIT = 5000;

export default function RegisterScoredDatasetButton({ context }: { context: VisualAnalysisContext }) {
  const [status, setStatus] = useState<"idle" | "working" | "done" | "already" | "error">("idle");
  const [message, setMessage] = useState<string | null>(null);

  async function handleRegister() {
    if (!context.scoringRunId) return;
    setStatus("working");
    setMessage(null);
    try {
      const run = await getScoringRun(context.scoringRunId);
      if (run.registrationStatus === "registered") {
        setStatus("already");
        setMessage(`Already registered as dataset ${run.outputDatasetId ?? "(unknown)"}.`);
        return;
      }
      const bounded = await getScoringRunRows(context.scoringRunId, REGISTRATION_ROW_LIMIT);
      const response = await registerScoredDataset({
        projectId: context.projectId,
        datasetType: (run.partition as "train" | "test" | "oot") ?? "scored",
        task: run.problemType ?? context.problemType ?? undefined,
        modelName: run.modelId ?? undefined,
        targetColumn: run.target ?? undefined,
        predictionColumn: run.predictionColumn ?? undefined,
        scoreColumn: run.probabilityColumn ?? undefined,
        residualColumn: run.residualColumn ?? undefined,
        rows: bounded.rows,
        metadata: {
          rowScope: bounded.truncated ? "bounded_sample" : "full_scored_output",
          limitation: bounded.truncated
            ? `Registered from a bounded sample of ${REGISTRATION_ROW_LIMIT.toLocaleString()} rows (of ${bounded.totalRowCount.toLocaleString()} total) to avoid transferring the full scoring run through the browser.`
            : undefined,
        },
        scoringRunId: context.scoringRunId,
      });
      setStatus("done");
      setMessage(`Registered as dataset ${response.dataset.datasetId}.`);
    } catch (err) {
      setStatus("error");
      setMessage(err instanceof Error ? err.message : "Registration failed.");
    }
  }

  return (
    <span className="inline-flex items-center gap-2">
      <button type="button" data-testid="va-register-scored-dataset" className="atlas-secondary-button text-xs" onClick={handleRegister} disabled={status === "working"}>
        {status === "working" ? "Registering..." : "Register Scored Dataset"}
      </button>
      {message ? <span role="status" aria-live="polite" className="text-xs text-slate-600" data-testid="va-register-status">{message}</span> : null}
    </span>
  );
}
