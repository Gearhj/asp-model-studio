import type { WorkflowStep } from "../config/workflows";
import type { ExperimentalDesignAnalysis } from "./experimentalDesign";
import { professionalTableHtml, sectionSummaryHtml } from "./reportFormatting";

export type WorkflowNodeEvidence = {
  stepId: string;
  stepLabel: string;
  objective?: string;
  inputs?: string;
  assumptions?: string;
  method?: string;
  metrics?: string[];
  validation?: string;
  risks?: string;
  decision?: string;
  rationale?: string;
  notes?: string;
  numeric?: Record<string, number>;
  analysisSnapshot?: ExperimentalDesignAnalysis;
  simulationResults?: Record<string, any>;
};

const STORAGE_KEY = "atlas-workflow-node-state";

function safeString(value: unknown) {
  return typeof value === "string" ? value : "";
}

export function loadWorkflowNodeEvidence(projectId: string, steps: WorkflowStep[]): WorkflowNodeEvidence[] {
  if (typeof localStorage === "undefined") return [];
  return steps.map((step) => {
    try {
      const raw = localStorage.getItem(`${STORAGE_KEY}:${projectId}:${step.id}`);
      const parsed = raw ? JSON.parse(raw) : {};
      return {
        stepId: step.id,
        stepLabel: step.label,
        objective: safeString(parsed.objective),
        inputs: safeString(parsed.inputs),
        assumptions: safeString(parsed.assumptions),
        method: safeString(parsed.method),
        metrics: Array.isArray(parsed.metrics) ? parsed.metrics.map(String) : [],
        validation: safeString(parsed.validation),
        risks: safeString(parsed.risks),
        decision: safeString(parsed.decision),
        rationale: safeString(parsed.rationale),
        notes: safeString(parsed.notes),
        numeric: parsed.numeric && typeof parsed.numeric === "object" ? parsed.numeric : undefined,
        analysisSnapshot: parsed.analysisSnapshot && typeof parsed.analysisSnapshot === "object" ? parsed.analysisSnapshot : undefined,
        simulationResults: parsed.simulationResults && typeof parsed.simulationResults === "object" ? parsed.simulationResults : undefined,
      };
    } catch {
      return { stepId: step.id, stepLabel: step.label };
    }
  });
}

export function summarizeWorkflowNodeEvidence(evidence: WorkflowNodeEvidence[]) {
  const captured = evidence.filter((row) =>
    [row.objective, row.inputs, row.assumptions, row.method, row.validation, row.risks, row.decision, row.rationale, row.notes]
      .some((value) => value?.trim()) || (row.metrics?.length ?? 0) > 0 || Boolean(row.simulationResults)
  );
  if (!captured.length) return "No workflow-node evidence has been captured yet.";
  const completed = captured.filter((row) => /approve|complete|proceed|ready/i.test(row.decision ?? "")).length;
  const summary = sectionSummaryHtml(
    "Workflow Evidence Summary",
    `${captured.length} workflow stage${captured.length === 1 ? "" : "s"} contain documented evidence. ${completed} stage${completed === 1 ? "" : "s"} include approval or proceed language. Review unresolved risks and rationale before final governance sign-off.`
  );
  const rows = captured.map((row) => [
    row.stepLabel,
    row.objective || "-",
    row.method || "-",
    row.metrics?.join(", ") || "-",
    row.validation || "-",
    row.decision || "-",
    row.rationale || "-",
    row.simulationResults
      ? `Mean power ${(Number(row.simulationResults.meanPower ?? 0) * 100).toFixed(1)}%; wrong-winner ${(Number(row.simulationResults.wrongWinnerRate ?? 0) * 100).toFixed(1)}%; action ${row.simulationResults.recommendedAction ?? "-"}`
      : "-",
  ]);
  return [
    summary,
    professionalTableHtml(
      ["Step", "Objective", "Method", "Metrics", "Validation", "Decision", "Rationale", "Simulation Evidence"],
      rows,
      { wide: true, badgeColumns: ["Decision"] }
    ),
  ].join("\n");
}
