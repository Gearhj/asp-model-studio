export type TimeSeriesPageKey =
  | "project-context"
  | "data-acquisition"
  | "profile"
  | "feature-calendar-design"
  | "backtest-design"
  | "model-configuration"
  | "train-backtest"
  | "forecast-results"
  | "diagnostics-stability"
  | "scenario-stress"
  | "recommendation-monitoring"
  | "documentation";

export type TimeSeriesLayout =
  | "charter"
  | "mapping"
  | "profile"
  | "feature-builder"
  | "timeline"
  | "model-cards"
  | "run-results"
  | "forecast"
  | "diagnostics"
  | "scenario"
  | "monitoring"
  | "documentation";

export type TimeSeriesPageDefinition = {
  key: TimeSeriesPageKey;
  stepNumber: number;
  title: string;
  eyebrow: string;
  summary: string;
  evidenceType: string;
  layout: TimeSeriesLayout;
  controls: string[];
  stats: Array<[string, string, "good" | "warn" | "info"]>;
  panels: Array<{ title: string; body: string; items: string[] }>;
  code: string[];
};
