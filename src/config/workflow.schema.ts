export type StepId =
  | "dashboard"
  | "data-acquisition"
  | "eda"
  | "outlier-handling"
  | "missing-values"
  | "feature-engineering"
  | "data-balancing"
  | "model-training"
  | "evaluation"
  | "interpretation"
  | "scoring";

export interface WorkflowStep {
  id: StepId;
  title: string;
  description: string;
  requires?: StepId[];
}
