import { persistenceRequest } from "../lib/serverPersistence";
import type { AnalyticalRunResponse } from "../types/analyticsEngine";

export async function runAnalyticsEngine(analysisType: string, payload: Record<string, unknown>) {
  const endpoint = endpointByType[analysisType];
  if (!endpoint) throw new Error(`Unsupported analytical engine analysis type: ${analysisType}`);
  return persistenceRequest<{ ok: boolean } & AnalyticalRunResponse>(endpoint, { method: "POST", body: JSON.stringify(payload) });
}

const endpointByType: Record<string, string> = {
  descriptive_profile: "/analytics-engine/descriptive/profile",
  data_quality_profile: "/analytics-engine/data-quality/profile",
  classification_diagnostics: "/analytics-engine/classification/diagnostics",
  regression_diagnostics: "/analytics-engine/regression/diagnostics",
  time_series_profile: "/analytics-engine/time-series/profile",
  forecast_diagnostics: "/analytics-engine/forecasting/diagnostics",
  forecast_backtest: "/analytics-engine/forecasting/backtest",
  experiment_diagnostics: "/analytics-engine/experimentation/diagnostics",
  optimization_diagnostics: "/analytics-engine/optimization/diagnostics",
  llm_evaluation: "/analytics-engine/llm/evaluation",
  segment_diagnostics: "/analytics-engine/segments/diagnostics",
  fairness_diagnostics: "/analytics-engine/fairness/diagnostics",
};

export async function requestAnalyticalRun(type: keyof typeof endpointByType, payload: Record<string, unknown>) {
  return persistenceRequest<{ ok: boolean } & AnalyticalRunResponse>(endpointByType[type], { method: "POST", body: JSON.stringify(payload) });
}

export async function captureAnalyticalEvidence(runId: string) {
  return persistenceRequest(`/analytics-engine/runs/${encodeURIComponent(runId)}/capture-evidence`, { method: "POST" });
}
