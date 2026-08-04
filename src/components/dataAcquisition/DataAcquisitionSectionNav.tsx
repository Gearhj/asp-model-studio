import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Circle, LoaderCircle } from "lucide-react";

export type DataAcquisitionSectionState =
  | "complete"
  | "current"
  | "attention"
  | "pending";

export type DataAcquisitionSectionNavItem = {
  id: string;
  label: string;
  state: DataAcquisitionSectionState;
  unresolvedCount?: number;
};

const stateLabel: Record<DataAcquisitionSectionState, string> = {
  complete: "Complete",
  current: "In progress",
  attention: "Requires attention",
  pending: "Pending",
};

function StateIcon({ state }: { state: DataAcquisitionSectionState }) {
  if (state === "complete") return <CheckCircle2 size={14} aria-hidden="true" />;
  if (state === "current") return <LoaderCircle size={14} aria-hidden="true" />;
  if (state === "attention") return <AlertTriangle size={14} aria-hidden="true" />;
  return <Circle size={14} aria-hidden="true" />;
}

export default function DataAcquisitionSectionNav({
  items,
}: {
  items: DataAcquisitionSectionNavItem[];
}) {
  const [activeId, setActiveId] = useState(items[0]?.id ?? "");

  useEffect(() => {
    const sections = items
      .map((item) => document.getElementById(item.id))
      .filter((section): section is HTMLElement => Boolean(section));
    if (!sections.length || typeof IntersectionObserver === "undefined") return undefined;

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((left, right) => {
            const topDelta = Math.abs(left.boundingClientRect.top - 132) - Math.abs(right.boundingClientRect.top - 132);
            return topDelta || right.intersectionRatio - left.intersectionRatio;
          });
        const next = visible[0]?.target.id;
        if (next) setActiveId(next);
      },
      { rootMargin: "-112px 0px -62% 0px", threshold: [0, 0.05, 0.25, 0.6] },
    );
    sections.forEach((section) => observer.observe(section));
    return () => observer.disconnect();
  }, [items]);

  return (
    <nav
      className="sticky top-3 z-30 rounded-xl border border-slate-200 bg-white/95 p-2 shadow-md shadow-slate-900/10 backdrop-blur-xl"
      aria-label="Data Acquisition sections"
      data-testid="data-acquisition-section-nav"
    >
      <div className="grid grid-cols-2 gap-1 sm:grid-cols-3 xl:grid-cols-6">
        {items.map((item) => {
          const active = activeId === item.id;
          return (
            <button
              key={item.id}
              type="button"
              className={`flex min-w-0 items-center justify-between gap-2 rounded-lg border px-3 py-2 text-left text-xs font-semibold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 ${
                active
                  ? "border-blue-500 bg-blue-50 text-blue-950 shadow-sm"
                  : item.state === "attention"
                    ? "border-amber-200 bg-amber-50 text-amber-950 hover:border-amber-300"
                    : "border-transparent text-slate-700 hover:border-slate-200 hover:bg-slate-50"
              }`}
              aria-current={active ? "location" : undefined}
              aria-label={`${item.label}. ${stateLabel[item.state]}${item.unresolvedCount ? `. ${item.unresolvedCount} unresolved` : ""}`}
              onClick={() => {
                setActiveId(item.id);
                document.getElementById(item.id)?.scrollIntoView({ behavior: "smooth", block: "start" });
              }}
              data-section-target={item.id}
              data-section-state={item.state}
            >
              <span className="flex min-w-0 items-center gap-2">
                <span
                  className={
                    item.state === "complete"
                      ? "text-emerald-700"
                      : item.state === "attention"
                        ? "text-amber-700"
                        : item.state === "current"
                          ? "text-blue-700"
                          : "text-slate-400"
                  }
                >
                  <StateIcon state={item.state} />
                </span>
                <span className="truncate">{item.label}</span>
              </span>
              {typeof item.unresolvedCount === "number" && item.unresolvedCount > 0 ? (
                <span className="rounded-full bg-amber-200 px-1.5 py-0.5 text-[10px] font-bold tabular-nums text-amber-950">
                  {item.unresolvedCount}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>
    </nav>
  );
}
