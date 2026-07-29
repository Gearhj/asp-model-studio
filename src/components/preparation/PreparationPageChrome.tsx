import type React from "react";
import {
  ArrowRight,
  Check,
  ChevronDown,
  CircleDashed,
  FileCheck2,
  LockKeyhole,
  Pause,
  ShieldCheck,
} from "lucide-react";
import type {
  CarryForwardDisposition,
  PreparationCarryForwardItem,
  PreparationDocumentationStatus,
} from "../../lib/preparationGovernance";
import "./preparation-premium.css";

export type PreparationSummaryMetric = {
  label: string;
  value: React.ReactNode;
  detail?: string;
  tone?: "neutral" | "info" | "success" | "warning" | "danger";
};

export function PreparationPageIdentity({
  step,
  title,
  description,
  datasetName,
  datasetVersion,
  target,
  predictorCount,
  predictorManifest,
  documentationStatus,
  decisionState,
  appearance = "dark",
}: {
  step: string;
  title: string;
  description: string;
  datasetName: string;
  datasetVersion: string;
  target: string;
  predictorCount: number;
  predictorManifest: string;
  documentationStatus: PreparationDocumentationStatus | "unavailable";
  decisionState: string;
  appearance?: "dark" | "light";
}) {
  return (
    <header
      className={`prep-identity prep-identity--${appearance}`}
      data-testid="preparation-page-identity"
      aria-labelledby="preparation-page-title"
    >
      <div className="prep-identity__main">
        <div className="min-w-0">
          <div className="prep-identity__eyebrow">
            Predictive Modeling <span aria-hidden="true">/</span> {step}
          </div>
          <h1 id="preparation-page-title" className="prep-identity__title">
            {title}
          </h1>
          <p className="prep-identity__description">{description}</p>
        </div>
        <div className="prep-identity__state">
          <span className="prep-state-pill prep-state-pill--backend">
            <LockKeyhole size={13} /> Backend enforced
          </span>
          <span
            className={`prep-state-pill prep-state-pill--${
              documentationStatus === "confirmed"
                ? "success"
                : documentationStatus === "stale"
                  ? "warning"
                  : "neutral"
            }`}
          >
            <FileCheck2 size={13} />
            {documentationStatus === "confirmed"
              ? "MDD confirmed"
              : documentationStatus === "stale"
                ? "MDD stale"
                : "MDD draft"}
          </span>
          <span className="prep-state-pill prep-state-pill--info">
            <ShieldCheck size={13} /> {decisionState}
          </span>
        </div>
      </div>
      <div className="prep-context-ribbon" aria-label="Governed preparation context">
        <ContextItem label="Dataset" value={datasetName || "Registered dataset"} />
        <ContextItem label="Version" value={datasetVersion || "Unversioned"} />
        <ContextItem label="Target" value={target || "Not set"} />
        <ContextItem label="Predictors" value={predictorCount.toLocaleString()} />
        <ContextItem label="Manifest" value={predictorManifest || "Pending"} />
      </div>
    </header>
  );
}

export function PreparationGovernanceDisclosure({
  title = "Governance and upstream handoff",
  summary,
  children,
}: {
  title?: string;
  summary: string;
  children: React.ReactNode;
}) {
  return (
    <details
      className="prep-governance-disclosure"
      data-testid="preparation-governance-disclosure"
    >
      <summary>
        <span className="min-w-0">
          <strong>{title}</strong>
          <small>{summary}</small>
        </span>
        <ChevronDown size={16} aria-hidden="true" />
      </summary>
      <div className="prep-governance-disclosure__body">{children}</div>
    </details>
  );
}

function ContextItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="prep-context-ribbon__item">
      <span>{label}</span>
      <strong title={value}>{value}</strong>
    </div>
  );
}

export function PreparationQuickSummary({
  metrics,
  label = "Decision snapshot",
}: {
  metrics: PreparationSummaryMetric[];
  label?: string;
}) {
  return (
    <section
      className="prep-quick-summary"
      aria-label={label}
      data-testid="preparation-quick-summary"
    >
      <div className="prep-quick-summary__label">{label}</div>
      <div className="prep-quick-summary__grid">
        {metrics.map((metric) => (
          <div
            key={metric.label}
            className={`prep-summary-metric prep-summary-metric--${metric.tone ?? "neutral"}`}
          >
            <span>{metric.label}</span>
            <strong>{metric.value}</strong>
            {metric.detail ? <small>{metric.detail}</small> : null}
          </div>
        ))}
      </div>
    </section>
  );
}

export function CarryForwardPanel({
  items,
  sourceStatus,
  onDisposition,
}: {
  items: PreparationCarryForwardItem[];
  sourceStatus: string;
  onDisposition: (
    item: PreparationCarryForwardItem,
    disposition: CarryForwardDisposition,
  ) => void;
}) {
  return (
    <details className="prep-carry-forward" data-testid="eda-carry-forward">
      <summary>
        <span>
          <span className="prep-carry-forward__eyebrow">Governed EDA handoff</span>
          <strong>
            {items.length
              ? `${items.length} accepted finding${items.length === 1 ? "" : "s"} available as draft inputs`
              : "No destination-specific EDA findings require action"}
          </strong>
        </span>
        <span className="prep-state-pill prep-state-pill--neutral">
          Source {sourceStatus.replace(/_/g, " ")}
        </span>
      </summary>
      <div className="prep-carry-forward__body">
        <p>
          Carry-forward items never mutate this plan automatically. Accepting one
          records it as a governed destination input; treatment and
          materialization remain explicit.
        </p>
        {items.length ? (
          <div className="prep-carry-forward__list">
            {items.map((item) => (
              <article key={item.findingId} className="prep-carry-forward__item">
                <div>
                  <div className="prep-carry-forward__destination">
                    {item.destination || "Downstream preparation"}
                  </div>
                  <h3>{item.title}</h3>
                  <p>{item.recommendation}</p>
                  {item.suggestedTransformation ? (
                    <code>{item.suggestedTransformation}</code>
                  ) : null}
                </div>
                <div className="prep-carry-forward__actions">
                  <DispositionButton
                    active={item.disposition === "accepted"}
                    icon={Check}
                    label="Accept input"
                    onClick={() => onDisposition(item, "accepted")}
                  />
                  <DispositionButton
                    active={item.disposition === "deferred"}
                    icon={Pause}
                    label="Defer"
                    onClick={() => onDisposition(item, "deferred")}
                  />
                  <DispositionButton
                    active={item.disposition === "draft"}
                    icon={CircleDashed}
                    label="Keep draft"
                    onClick={() => onDisposition(item, "draft")}
                  />
                </div>
              </article>
            ))}
          </div>
        ) : null}
      </div>
    </details>
  );
}

function DispositionButton({
  active,
  icon: Icon,
  label,
  onClick,
}: {
  active: boolean;
  icon: typeof Check;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={active ? "prep-choice-button is-active" : "prep-choice-button"}
      onClick={onClick}
    >
      <Icon size={13} /> {label}
    </button>
  );
}

export function DecisionFlow({
  stages,
}: {
  stages: Array<{ label: string; detail: string; state?: string }>;
}) {
  return (
    <div className="prep-decision-flow" aria-label="Governed decision flow">
      {stages.map((stage, index) => (
        <div className="contents" key={stage.label}>
          <div className="prep-decision-flow__stage">
            <span>{stage.state ?? `0${index + 1}`}</span>
            <strong>{stage.label}</strong>
            <small>{stage.detail}</small>
          </div>
          {index < stages.length - 1 ? (
            <ArrowRight className="prep-decision-flow__arrow" size={18} />
          ) : null}
        </div>
      ))}
    </div>
  );
}
