// ATLAS Visual Intelligence Foundation, Phase 1 -- contained experimental panel hosting
// the three prototypes. Deliberately NOT wired into the Evaluation/Interpretation/Scoring
// workflow pages themselves (stop condition: "Do not broadly redesign Evaluation").
import { useEffect, useState } from "react";
import { VisualIntelligenceProvider, useVisualIntelligenceContext } from "../visual-intelligence/VisualIntelligenceContext";
import DistributionExplorer from "../visual-intelligence/prototypes/DistributionExplorer";
import ClassificationDecisionExplorer from "../visual-intelligence/prototypes/ClassificationDecisionExplorer";
import RegressionDiagnosticExplorer from "../visual-intelligence/prototypes/RegressionDiagnosticExplorer";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { listScoringRuns, type ScoringRunSummary } from "../scoring-runs/scoringRunClient";

type TabId = "distribution" | "classification" | "regression";

const TABS: Array<{ id: TabId; label: string }> = [
  { id: "distribution", label: "Interactive Distribution Explorer" },
  { id: "classification", label: "Classification Decision Explorer" },
  { id: "regression", label: "Regression Diagnostic Explorer" },
];

function ScoringRunSelector() {
  const projectId = useWorkflowStore((state) => state.projectId);
  const { scoringRunId, selectScoringRun } = useVisualIntelligenceContext();
  const [runs, setRuns] = useState<ScoringRunSummary[]>([]);

  useEffect(() => {
    let cancelled = false;
    if (!projectId) return;
    listScoringRuns(projectId, { limit: 25 })
      .then((result) => {
        if (!cancelled) setRuns(result);
      })
      .catch(() => {
        if (!cancelled) setRuns([]);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  return (
    <div className="flex items-center gap-2 text-sm" data-testid="vi-scoring-run-selector">
      <label htmlFor="vi-scoring-run-select" className="font-medium text-slate-700">
        Data source
      </label>
      <select
        id="vi-scoring-run-select"
        data-testid="vi-scoring-run-select"
        className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
        value={scoringRunId ?? ""}
        onChange={(event) => selectScoringRun(event.target.value || null)}
      >
        <option value="">Live workspace data</option>
        {runs.map((run) => (
          <option key={run.scoringRunId} value={run.scoringRunId}>
            {run.partition.toUpperCase()} -- {run.modelId ?? "model"} -- {new Date(run.createdAt).toLocaleString()}
          </option>
        ))}
      </select>
      {scoringRunId ? (
        <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-semibold text-blue-800" data-testid="vi-scoring-run-badge">
          Durable scoring run
        </span>
      ) : (
        <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800">Session-scoped</span>
      )}
    </div>
  );
}

export default function VisualIntelligenceLab() {
  const [tab, setTab] = useState<TabId>("distribution");

  return (
    <VisualIntelligenceProvider>
      <div className="mx-auto max-w-6xl space-y-5 p-6">
        <header className="space-y-3">
          <h1 className="text-xl font-semibold text-slate-950">Visual Intelligence Lab</h1>
          <p className="mt-1 max-w-3xl text-sm text-slate-600">
            Experimental panel for the ATLAS Visual Intelligence Foundation (Phase 1). These three prototypes demonstrate the
            reusable D3 + Apache ECharts + DuckDB-Wasm architecture against the currently active project's real training data.
            They do not replace or modify the existing Evaluation, Interpretation, or Scoring pages.
          </p>
          <p className="max-w-3xl text-sm text-slate-600">
            Select a durable Scoring Run to view its persisted TRAIN/TEST/OOT results -- a page refresh reloads the same run
            (its id lives in the URL), unlike live workspace data, which is session-scoped.
          </p>
          <ScoringRunSelector />
        </header>

        <nav className="flex flex-wrap gap-2 border-b border-slate-200 pb-2" role="tablist" aria-label="Visual Intelligence prototypes">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={tab === t.id}
              data-testid={`vi-tab-${t.id}`}
              onClick={() => setTab(t.id)}
              className={`rounded-md px-3 py-2 text-sm font-semibold ${tab === t.id ? "bg-slate-950 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"}`}
            >
              {t.label}
            </button>
          ))}
        </nav>

        <div role="tabpanel">
          {tab === "distribution" ? <DistributionExplorer /> : null}
          {tab === "classification" ? <ClassificationDecisionExplorer /> : null}
          {tab === "regression" ? <RegressionDiagnosticExplorer /> : null}
        </div>
      </div>
    </VisualIntelligenceProvider>
  );
}
