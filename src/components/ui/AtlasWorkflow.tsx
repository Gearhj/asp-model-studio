import type React from "react";
import type { LucideIcon } from "lucide-react";
import {
  AlertTriangle,
  CheckCircle2,
  Circle,
  Clock3,
  LoaderCircle,
  ShieldCheck,
  XCircle,
} from "lucide-react";

export type AtlasWorkflowVariant = "standard" | "data" | "analysis" | "preparation" | "modeling";
export type AtlasWorkflowTone = "neutral" | "info" | "success" | "warning" | "danger";

export type AtlasWorkflowMetric = {
  label: string;
  value: React.ReactNode;
  detail?: string;
  tone?: AtlasWorkflowTone;
};

export type AtlasStatusItem = {
  label: string;
  state: "complete" | "current" | "pending" | "warning" | "blocked";
  detail?: string;
};

const metricToneClass: Record<AtlasWorkflowTone, string> = {
  neutral: "atlas-workflow-metric--neutral",
  info: "atlas-workflow-metric--info",
  success: "atlas-workflow-metric--success",
  warning: "atlas-workflow-metric--warning",
  danger: "atlas-workflow-metric--danger",
};

export function AtlasWorkflowHero({
  eyebrow,
  title,
  description,
  variant = "standard",
  metrics = [],
  action,
  children,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  variant?: AtlasWorkflowVariant;
  metrics?: AtlasWorkflowMetric[];
  action?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <header className={`atlas-workflow-hero atlas-workflow-hero--${variant}`} data-workflow-variant={variant}>
      <div className="atlas-workflow-hero__content">
        <div className="min-w-0 flex-1">
          {eyebrow ? <div className="atlas-workflow-hero__eyebrow">{eyebrow}</div> : null}
          <h1 className="atlas-workflow-hero__title">{title}</h1>
          {description ? <p className="atlas-workflow-hero__description">{description}</p> : null}
          {children ? <div className="mt-4">{children}</div> : null}
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
      {metrics.length ? (
        <div className={`atlas-workflow-hero__metrics ${variant === "modeling" ? "atlas-workflow-hero__metrics--modeling" : ""}`}>
          {metrics.map((metric) => (
            <div key={metric.label} className={`atlas-workflow-metric ${metricToneClass[metric.tone ?? "neutral"]}`}>
              <div className="atlas-workflow-metric__label">{metric.label}</div>
              <div className="atlas-workflow-metric__value" title={typeof metric.value === "string" ? metric.value : undefined}>
                {metric.value}
              </div>
              {metric.detail ? <div className="atlas-workflow-metric__detail">{metric.detail}</div> : null}
            </div>
          ))}
        </div>
      ) : null}
    </header>
  );
}

const sectionToneClass: Record<AtlasWorkflowTone, string> = {
  neutral: "atlas-workflow-section--neutral",
  info: "atlas-workflow-section--info",
  success: "atlas-workflow-section--success",
  warning: "atlas-workflow-section--warning",
  danger: "atlas-workflow-section--danger",
};

export function AtlasWorkflowSection({
  title,
  eyebrow,
  description,
  tone = "neutral",
  action,
  children,
  className = "",
  id,
}: {
  title?: string;
  eyebrow?: string;
  description?: string;
  tone?: AtlasWorkflowTone;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section id={id} className={`atlas-workflow-section ${sectionToneClass[tone]} ${className}`}>
      {title || eyebrow || description || action ? (
        <div className="atlas-workflow-section__header">
          <div className="min-w-0">
            {eyebrow ? <div className="atlas-workflow-section__eyebrow">{eyebrow}</div> : null}
            {title ? <h2 className="atlas-workflow-section__title">{title}</h2> : null}
            {description ? <p className="atlas-workflow-section__description">{description}</p> : null}
          </div>
          {action ? <div className="shrink-0">{action}</div> : null}
        </div>
      ) : null}
      {children}
    </section>
  );
}

const statusIcon = {
  complete: <CheckCircle2 size={16} />,
  current: <LoaderCircle size={16} />,
  pending: <Circle size={16} />,
  warning: <AlertTriangle size={16} />,
  blocked: <XCircle size={16} />,
};

export function AtlasStatusStrip({ items, label }: { items: AtlasStatusItem[]; label?: string }) {
  return (
    <div className="atlas-status-strip" aria-label={label ?? "Workflow status"}>
      {items.map((item, index) => (
        <div key={`${item.label}-${index}`} className={`atlas-status-strip__item atlas-status-strip__item--${item.state}`}>
          <span className="atlas-status-strip__icon" aria-hidden="true">{statusIcon[item.state]}</span>
          <span className="min-w-0">
            <span className="atlas-status-strip__label">{item.label}</span>
            {item.detail ? <span className="atlas-status-strip__detail">{item.detail}</span> : null}
          </span>
        </div>
      ))}
    </div>
  );
}

export function AtlasDataScopeBadge({
  scope,
  rows,
}: {
  scope: "full_dataset" | "complete_browser_dataset" | "preview_profile" | "rendered_sample" | "training_pipeline" | "unavailable";
  rows?: number | null;
}) {
  const content = {
    full_dataset: ["Full Dataset", "success"],
    complete_browser_dataset: ["Complete Browser Dataset", "info"],
    preview_profile: ["Preview Profile", "warning"],
    rendered_sample: ["Rendered Sample", "neutral"],
    training_pipeline: ["Training-Only Pipeline", "info"],
    unavailable: ["Scope Unavailable", "danger"],
  }[scope] as [string, AtlasWorkflowTone];
  return (
    <span className={`atlas-data-scope atlas-data-scope--${content[1]}`}>
      <ShieldCheck size={14} aria-hidden="true" />
      {content[0]}{typeof rows === "number" ? `: ${rows.toLocaleString()} Rows` : ""}
    </span>
  );
}

export function AtlasExecutionStatus({
  state,
  label,
  detail,
}: {
  state: "idle" | "queued" | "preparing" | "running" | "complete" | "failed" | "cancelled" | "interrupted";
  label?: string;
  detail?: string;
}) {
  const config: Record<typeof state, [LucideIcon, string]> = {
    idle: [Circle, "Not started"],
    queued: [Clock3, "Queued"],
    preparing: [LoaderCircle, "Preparing"],
    running: [LoaderCircle, "Running"],
    complete: [CheckCircle2, "Complete"],
    failed: [XCircle, "Failed"],
    cancelled: [XCircle, "Cancelled"],
    interrupted: [AlertTriangle, "Interrupted"],
  };
  const selectedConfig = config[state];
  const Icon = selectedConfig[0];
  return (
    <div className={`atlas-execution-status atlas-execution-status--${state}`}>
      <Icon size={17} className={state === "preparing" || state === "running" ? "animate-spin" : ""} aria-hidden="true" />
      <span className="min-w-0">
        <span className="block font-semibold">{label ?? selectedConfig[1]}</span>
        {detail ? <span className="mt-0.5 block text-xs opacity-75">{detail}</span> : null}
      </span>
    </div>
  );
}

export function AtlasAttentionPanel({
  title,
  children,
  tone = "warning",
}: {
  title: string;
  children: React.ReactNode;
  tone?: "info" | "warning" | "danger";
}) {
  const Icon = tone === "info" ? ShieldCheck : tone === "danger" ? XCircle : AlertTriangle;
  return (
    <div className={`atlas-attention atlas-attention--${tone}`} role={tone === "danger" ? "alert" : undefined}>
      <Icon size={18} className="mt-0.5 shrink-0" aria-hidden="true" />
      <div>
        <div className="font-semibold">{title}</div>
        <div className="mt-1 text-sm leading-6">{children}</div>
      </div>
    </div>
  );
}
