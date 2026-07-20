export type LlmPageKey =
  | "use-case-risk"
  | "sources"
  | "task-schema"
  | "prompt"
  | "rag"
  | "evaluation-dataset"
  | "llm-evaluation"
  | "safety"
  | "human-review"
  | "deployment"
  | "recommendation"
  | "documentation";

export type LlmLayout =
  | "risk"
  | "sources"
  | "schema"
  | "prompt"
  | "rag"
  | "eval-data"
  | "eval-run"
  | "safety"
  | "review"
  | "deployment"
  | "recommendation"
  | "documentation";

export type LlmPageDefinition = {
  key: LlmPageKey;
  stepNumber: number;
  title: string;
  eyebrow: string;
  summary: string;
  evidenceType: string;
  layout: LlmLayout;
  controls: string[];
  stats: Array<[string, string, "good" | "warn" | "info"]>;
  panels: Array<{ title: string; body: string; items: string[] }>;
  code: string[];
};
