import { useEffect, useId, useRef, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

export type CockpitDrawerProps = {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  eyebrow?: string;
  children: ReactNode;
  footer?: ReactNode;
  initialFocusRef?: RefObject<HTMLElement>;
  returnFocusRef?: RefObject<HTMLElement>;
  side?: "left" | "right";
  widthClassName?: string;
  testId?: string;
};

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

/**
 * Shared accessible drawer for the focused modeling cockpit.
 *
 * The drawer is rendered in the document top layer, traps keyboard focus,
 * makes the application behind it inert, and returns focus to the control
 * that opened it. Its interaction contract is intentionally independent of
 * any workflow or analytical state.
 */
export function CockpitDrawer({
  open,
  onClose,
  title,
  description,
  eyebrow,
  children,
  footer,
  initialFocusRef,
  returnFocusRef,
  side = "right",
  widthClassName = "max-w-2xl",
  testId,
}: CockpitDrawerProps) {
  const titleId = useId();
  const descriptionId = useId();
  const panelRef = useRef<HTMLElement>(null);
  const priorFocusRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return undefined;

    priorFocusRef.current = returnFocusRef?.current ?? (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    const applicationRoot = document.getElementById("root");
    const previousRootInert = applicationRoot?.inert ?? false;
    const previousRootAriaHidden = applicationRoot ? applicationRoot.getAttribute("aria-hidden") : null;
    const previousBodyOverflow = document.body.style.overflow;

    const focusFirst = () => {
      const requested = initialFocusRef?.current;
      const firstFocusable = panelRef.current?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
      (requested ?? firstFocusable ?? panelRef.current)?.focus();
    };
    // Move focus into the portal before hiding the application root. This
    // avoids leaving the trigger as a focused descendant of aria-hidden.
    focusFirst();
    if (applicationRoot) {
      applicationRoot.inert = true;
      applicationRoot.setAttribute("aria-hidden", "true");
    }
    document.body.style.overflow = "hidden";
    const animationFrame = window.requestAnimationFrame(focusFirst);

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !panelRef.current) return;

      const focusable = [...panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)]
        .filter((element) => !element.hidden && element.getAttribute("aria-hidden") !== "true");
      if (!focusable.length) {
        event.preventDefault();
        panelRef.current.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      } else if (!panelRef.current.contains(document.activeElement)) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);

    return () => {
      window.cancelAnimationFrame(animationFrame);
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousBodyOverflow;
      if (applicationRoot) {
        applicationRoot.inert = previousRootInert;
        if (previousRootAriaHidden === null) applicationRoot.removeAttribute("aria-hidden");
        else applicationRoot.setAttribute("aria-hidden", previousRootAriaHidden);
      }
      window.requestAnimationFrame(() => (returnFocusRef?.current ?? priorFocusRef.current)?.focus());
    };
  }, [initialFocusRef, open, returnFocusRef]);

  if (!open || typeof document === "undefined") return null;

  return createPortal(
    <div
      className={`fixed inset-0 z-[110] flex bg-slate-950/45 backdrop-blur-[1px] ${side === "right" ? "justify-end" : "justify-start"}`}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      data-testid={testId}
    >
      <aside
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
        className={`flex h-full w-full flex-col overflow-hidden bg-white shadow-2xl ${widthClassName} ${side === "right" ? "border-l border-slate-200" : "border-r border-slate-200"}`}
      >
        <header className="sticky top-0 z-10 flex shrink-0 items-start gap-3 border-b border-slate-200 bg-white px-4 py-4 sm:px-5">
          <div className="min-w-0 flex-1">
            {eyebrow ? <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-cyan-700">{eyebrow}</div> : null}
            <h2 id={titleId} className="mt-0.5 text-xl font-semibold tracking-tight text-slate-950">{title}</h2>
            {description ? <p id={descriptionId} className="mt-1 text-xs leading-5 text-slate-600">{description}</p> : null}
          </div>
          <button type="button" onClick={onClose} aria-label={`Close ${title}`} className="shrink-0 rounded-lg border border-slate-200 p-2 text-slate-500 hover:bg-slate-50 hover:text-slate-900 focus:outline-none focus:ring-2 focus:ring-cyan-500">
            <X size={17} aria-hidden="true" />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden">{children}</div>
        {footer ? <footer className="sticky bottom-0 z-10 shrink-0 border-t border-slate-200 bg-white px-4 py-3 sm:px-5">{footer}</footer> : null}
      </aside>
    </div>,
    document.body,
  );
}
