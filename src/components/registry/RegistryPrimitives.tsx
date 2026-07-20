import type React from "react";
import AtlasStatusBadge from "../ui/AtlasStatusBadge";

export const ASSET_TYPE_LABELS: Record<string, string> = {
  predictive_model: "Predictive Model",
  credit_risk_model: "Credit Risk Model",
  forecasting_study: "Forecasting Study",
  time_series_model: "Time Series Model",
  llm_workflow: "LLM Workflow",
  generative_ai_workflow: "Generative AI Workflow",
  optimization_study: "Optimization Study",
  experiment: "Experiment",
  ab_test: "A/B Test",
  decision_strategy: "Decision Strategy",
  custom_workflow: "Custom Workflow",
};

export const TEMPLATE_LABELS: Record<string, string> = {
  transportation_logistics: "Transportation / Logistics",
  time_series_forecasting: "Time Series & Forecasting",
  llm_generative_ai: "LLM / Generative AI",
};

export const LIFECYCLE_ORDER = [
  "Draft",
  "Development",
  "Ready for Review",
  "Validation",
  "Recommended",
  "Approved",
  "Approved with Conditions",
  "Implementation Planned",
  "Implemented",
  "Monitoring",
] as const;

export function humanize(value: unknown, fallback = "Not recorded") {
  const text = String(value ?? "").trim();
  if (!text) return fallback;
  return text
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function formatRegistryDate(value: string | null | undefined, includeTime = false) {
  if (!value) return "Not recorded";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Not recorded";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    ...(includeTime ? { hour: "numeric", minute: "2-digit" } : {}),
  }).format(date);
}

export function statusTone(status: unknown): "neutral" | "info" | "success" | "warning" | "danger" {
  const key = String(status ?? "").trim().toLowerCase();
  if (key === "high") return "danger";
  if (key === "medium") return "warning";
  if (key === "low") return "neutral";
  if (["approved", "approved with conditions", "complete", "completed", "ready", "recommended", "implemented", "monitoring", "active", "plan complete", "open"].includes(key)) return "success";
  if (["development", "validation", "independent validation in progress", "in progress", "implementation planned", "running", "captured", "submitted for independent validation"].includes(key)) return "info";
  if (["draft", "pending", "not submitted", "not started", "incomplete", "generated", "returned", "returned to owner", "remediation required", "stale"].includes(key)) return "warning";
  if (["rejected", "failed", "failure", "blocked", "missing"].includes(key)) return "danger";
  return "neutral";
}

export function RegistryStatus({ value, className = "" }: { value: unknown; className?: string }) {
  return <AtlasStatusBadge tone={statusTone(value)} className={className}>{String(value || "Not recorded")}</AtlasStatusBadge>;
}

export function PortfolioBar({ label, value, total, color = "bg-blue-600", detail }: { label: string; value: number; total: number; color?: string; detail?: React.ReactNode }) {
  const percent = total > 0 ? Math.max(value > 0 ? 4 : 0, Math.round((value / total) * 100)) : 0;
  return (
    <div className="grid gap-2 py-2 sm:grid-cols-[180px_minmax(0,1fr)_54px] sm:items-center">
      <div className="truncate text-sm font-medium text-slate-700" title={label}>{label}</div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-100" aria-label={`${label}: ${value}`}>
        <div className={`h-full rounded-full ${color}`} style={{ width: `${percent}%` }} />
      </div>
      <div className="text-right text-sm font-semibold tabular-nums text-slate-950">{value}</div>
      {detail && <div className="sm:col-start-2 sm:col-span-2 text-xs text-slate-500">{detail}</div>}
    </div>
  );
}

export function MetricPair({ label, value, valueClassName = "" }: { label: string; value: React.ReactNode; valueClassName?: string }) {
  return (
    <div className="min-w-0 border-b border-slate-100 py-3 last:border-b-0">
      <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">{label}</div>
      <div className={`mt-1 break-words text-sm font-semibold text-slate-950 ${valueClassName}`}>{value}</div>
    </div>
  );
}
