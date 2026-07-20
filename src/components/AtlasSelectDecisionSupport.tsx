import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { BookOpenCheck, CircleHelp, X } from "lucide-react";
import { getSelectionGuidance } from "../lib/selectDecisionSupport";

type ActiveSelection = {
  label: string;
  value: string;
  options: string[];
  rect: DOMRect;
};

const DISABLED_PATHS = new Set(["/step01", "/step02", "/step06"]);

function cleanLabel(value: string) {
  return value
    .replace(/\s+/g, " ")
    .replace(/\b(select|choose)\b.*$/i, "")
    .replace(/[\s:]+$/, "")
    .trim();
}

function selectLabel(select: HTMLSelectElement) {
  const explicit = select.dataset.guidanceLabel || select.getAttribute("aria-label") || select.getAttribute("title");
  if (explicit) return cleanLabel(explicit);
  const labelledBy = select.getAttribute("aria-labelledby");
  if (labelledBy) {
    const text = labelledBy
      .split(/\s+/)
      .map((id) => document.getElementById(id)?.textContent ?? "")
      .join(" ");
    if (text.trim()) return cleanLabel(text);
  }
  if (select.id) {
    const label = document.querySelector<HTMLLabelElement>(`label[for="${CSS.escape(select.id)}"]`);
    if (label?.textContent) return cleanLabel(label.textContent);
  }
  const wrappingLabel = select.closest("label");
  if (wrappingLabel) {
    const labelText = Array.from(wrappingLabel.childNodes)
      .filter((node) => node !== select)
      .map((node) => node.textContent ?? "")
      .join(" ");
    if (labelText.trim()) return cleanLabel(labelText);
  }
  return cleanLabel(select.name || select.id || "Selection");
}

function readSelection(select: HTMLSelectElement): ActiveSelection {
  return {
    label: selectLabel(select),
    value: select.value ? select.selectedOptions[0]?.textContent?.trim() || select.value : "",
    options: Array.from(select.options).map((option) => option.textContent?.trim() || option.value).filter(Boolean),
    rect: select.getBoundingClientRect(),
  };
}

export default function AtlasSelectDecisionSupport() {
  const [active, setActive] = useState<ActiveSelection | null>(null);

  useEffect(() => {
    if (DISABLED_PATHS.has(window.location.pathname)) {
      setActive(null);
      return;
    }
    const showForEvent = (event: Event) => {
      if (DISABLED_PATHS.has(window.location.pathname)) {
        setActive(null);
        return;
      }
      const target = event.target;
      if (target instanceof HTMLSelectElement && !target.disabled) setActive(readSelection(target));
    };
    const closeForPointer = (event: PointerEvent) => {
      const target = event.target;
      if (target instanceof HTMLSelectElement || (target instanceof Element && target.closest("[data-atlas-select-guide]"))) return;
      setActive(null);
    };
    const closeForKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setActive(null);
    };
    const reposition = () => {
      const focused = document.activeElement;
      if (focused instanceof HTMLSelectElement) setActive(readSelection(focused));
    };
    document.addEventListener("focusin", showForEvent, true);
    document.addEventListener("pointerdown", showForEvent, true);
    document.addEventListener("change", showForEvent, true);
    document.addEventListener("pointerdown", closeForPointer, false);
    document.addEventListener("keydown", closeForKey);
    window.addEventListener("resize", reposition);
    window.addEventListener("scroll", reposition, true);
    return () => {
      document.removeEventListener("focusin", showForEvent, true);
      document.removeEventListener("pointerdown", showForEvent, true);
      document.removeEventListener("change", showForEvent, true);
      document.removeEventListener("pointerdown", closeForPointer, false);
      document.removeEventListener("keydown", closeForKey);
      window.removeEventListener("resize", reposition);
      window.removeEventListener("scroll", reposition, true);
    };
  }, []);

  const guidance = useMemo(
    () => active
      ? getSelectionGuidance({ label: active.label, value: active.value, options: active.options }) ?? {
          definition: `This control has ${Math.max(0, active.options.length - 1)} available analytical choices. Review their fit before selecting one.`,
          useWhen: "Choose only after matching the option's assumptions, data requirements, decision purpose, and governance implications to the project.",
          example: "Open Compare available options below, then select the choice whose use case matches the current decision.",
        }
      : null,
    [active],
  );

  if (!active || !guidance || typeof document === "undefined") return null;
  const width = Math.min(390, Math.max(300, window.innerWidth - 24));
  const desiredLeft = active.rect.left;
  const left = Math.max(12, Math.min(desiredLeft, window.innerWidth - width - 12));
  const estimatedHeight = guidance.caution ? 290 : 245;
  const below = active.rect.bottom + 8;
  const top = below + estimatedHeight <= window.innerHeight
    ? below
    : Math.max(12, active.rect.top - estimatedHeight - 8);
  const comparableOptions = active.options
    .filter((option) => option !== active.value && !/^(select|choose|loading|not mapped)/i.test(option))
    .slice(0, 8);

  return createPortal(
    <aside
      data-atlas-select-guide
      data-testid="atlas-select-decision-support"
      className="fixed z-[100] overflow-y-auto rounded-xl border border-blue-200 bg-white shadow-2xl shadow-slate-950/20"
      style={{ width, left, top, maxHeight: Math.max(320, window.innerHeight - 24) }}
      role="status"
      aria-live="polite"
    >
      <div className="flex items-start justify-between gap-3 bg-slate-950 px-4 py-3 text-white">
        <div className="flex min-w-0 items-start gap-2.5">
          <CircleHelp size={18} className="mt-0.5 shrink-0 text-sky-300" />
          <div className="min-w-0">
            <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-sky-200">How to choose</div>
            <div className="mt-0.5 truncate text-sm font-semibold">{active.label || "Selection guidance"}</div>
          </div>
        </div>
        <button type="button" className="rounded-md p-1 text-slate-300 hover:bg-white/10 hover:text-white" onClick={() => setActive(null)} title="Close selection guidance">
          <X size={16} />
        </button>
      </div>
      <div className="space-y-3 px-4 py-3 text-xs leading-5 text-slate-700">
        <div className="rounded-lg border border-blue-100 bg-blue-50 px-3 py-2">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-blue-700">Selected option</div>
          <div className="mt-0.5 font-semibold text-slate-950">{active.value || "No option selected"}</div>
        </div>
        <div><span className="font-semibold text-slate-950">Definition:</span> {guidance.definition}</div>
        <div><span className="font-semibold text-slate-950">Best used when:</span> {guidance.useWhen}</div>
        <div><span className="font-semibold text-slate-950">Avoid when:</span> {guidance.avoidWhen || guidance.caution || "The option's assumptions, data requirements, or operational meaning do not match the current decision."}</div>
        <div className="flex items-start gap-2 rounded-lg border border-emerald-100 bg-emerald-50 px-3 py-2 text-emerald-950">
          <BookOpenCheck size={15} className="mt-0.5 shrink-0" />
          <div><span className="font-semibold">Example:</span> {guidance.example}</div>
        </div>
        <div><span className="font-semibold text-slate-950">Effect on formulation or solver:</span> {guidance.formulationEffect || "This choice changes how ATLAS interprets the selected role and carries it into the analytical configuration."}</div>
        <div><span className="font-semibold text-slate-950">Evidence implication:</span> {guidance.evidenceImplication || "ATLAS records the selected option with its project, source, user, and downstream analytical artifacts."}</div>
        <div><span className="font-semibold text-slate-950">Downstream impact:</span> {guidance.downstreamImpact || "Downstream checks, recommendations, and reproducibility outputs inherit this selection until it is changed and rerun."}</div>
        {guidance.caution && <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-amber-950"><span className="font-semibold">Watch for:</span> {guidance.caution}</div>}
        {comparableOptions.length >= 2 && comparableOptions.length <= 8 && (
          <details className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
            <summary className="cursor-pointer font-semibold text-slate-900">Compare available options ({comparableOptions.length})</summary>
            <div className="mt-2 max-h-52 space-y-2 overflow-auto border-t border-slate-200 pt-2">
              {comparableOptions.map((option) => {
                const optionGuidance = getSelectionGuidance({ label: active.label, value: option, options: active.options });
                return (
                  <div key={option} className="border-b border-slate-200 pb-2 last:border-0 last:pb-0">
                    <div className="font-semibold text-slate-950">{option}</div>
                    <div className="mt-0.5 text-slate-600">{optionGuidance?.definition}</div>
                  </div>
                );
              })}
            </div>
          </details>
        )}
      </div>
    </aside>,
    document.body,
  );
}
