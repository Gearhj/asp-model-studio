import type React from "react";

type AtlasCardProps = {
  children: React.ReactNode;
  className?: string;
  title?: string;
  eyebrow?: string;
  action?: React.ReactNode;
  tone?: "default" | "subtle" | "info" | "success" | "warning" | "attention";
};

const toneClass = {
  default: "atlas-card",
  subtle: "atlas-card-subtle",
  info: "atlas-info-panel",
  success: "atlas-success-panel",
  warning: "atlas-warning-panel",
  attention: "atlas-attention-panel",
};

export default function AtlasCard({ children, className = "", title, eyebrow, action, tone = "default" }: AtlasCardProps) {
  return (
    <section className={`${toneClass[tone]} ${className}`}>
      {(title || eyebrow || action) && (
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            {eyebrow && <div className="atlas-eyebrow">{eyebrow}</div>}
            {title && <h2 className="mt-1 atlas-section-title">{title}</h2>}
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}
