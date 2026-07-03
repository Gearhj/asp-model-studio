import type { DecisionJournalEntry } from "./decisionJournal";
import type { ExperimentRecord } from "./experimentTracking";

export type ReportReadinessItem = {
  item: string;
  status: "ready" | "warning" | "missing";
  evidence: string;
};

export type ReportReadinessSummary = {
  ready: boolean;
  checklist: ReportReadinessItem[];
  missingEvidence: string[];
};

export function buildReportReadiness(input: {
  problemType?: string | null;
  experiments: ExperimentRecord[];
  champion: ExperimentRecord | null;
  decisions: DecisionJournalEntry[];
  dataset?: { target?: string | null; selected_columns?: string[]; rows?: unknown[] } | null;
  context?: { businessObjective?: string; targetDefinition?: string; intendedModelUse?: string; primarySuccessMetric?: unknown };
}): ReportReadinessSummary {
  const checklist: ReportReadinessItem[] = [
    {
      item: "Project context",
      status: input.context?.businessObjective && input.context?.targetDefinition ? "ready" : "missing",
      evidence: input.context?.businessObjective ? "Business objective and target definition are available." : "Business objective or target definition is missing.",
    },
    {
      item: "Dataset and target",
      status: input.dataset?.target ? "ready" : "missing",
      evidence: input.dataset?.target ? `Target ${input.dataset.target} is selected.` : "No target variable is selected.",
    },
    {
      item: "Feature set",
      status: (input.dataset?.selected_columns?.length ?? 0) > 0 ? "ready" : "warning",
      evidence: `${input.dataset?.selected_columns?.length ?? 0} selected feature(s) are documented.`,
    },
    {
      item: "Candidate experiments",
      status: input.experiments.length ? "ready" : "missing",
      evidence: `${input.experiments.length} experiment record(s) are available.`,
    },
    {
      item: "Champion model",
      status: input.champion ? "ready" : "missing",
      evidence: input.champion ? `${input.champion.modelType} is marked as champion.` : "No champion model has been promoted.",
    },
    {
      item: "Performance evidence",
      status: input.champion?.metrics && Object.keys(input.champion.metrics).length ? "ready" : "missing",
      evidence: input.champion?.metrics && Object.keys(input.champion.metrics).length ? "Champion performance metrics are present." : "Champion metrics are missing.",
    },
    {
      item: "Decision rationale",
      status: input.decisions.length ? "ready" : "warning",
      evidence: `${input.decisions.length} decision journal event(s) are available.`,
    },
  ];
  const missingEvidence = checklist.filter((item) => item.status !== "ready").map((item) => `${item.item}: ${item.evidence}`);
  return {
    ready: missingEvidence.length === 0,
    checklist,
    missingEvidence,
  };
}
