// Shared render primitives for the one dataset action model.
//
// Card View and Detailed View render the SAME `DatasetAction` objects through
// these controls, so a tooltip, an accessible name, a disabled reason, or a
// confirmation can never drift between the two views.
import { useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  BarChart3,
  Download,
  FolderOpen,
  LineChart,
  Link2,
  MoreHorizontal,
  Share2,
  Table2,
  Trash2,
} from "lucide-react";
import type { DatasetAction, DatasetActionIcon } from "../../lib/datasetActions";

/** Resolves the model's framework-free icon id to a component. */
export function ActionIcon({ icon, size = 15 }: { icon: DatasetActionIcon; size?: number }) {
  switch (icon) {
    case "open":
      return <FolderOpen size={size} aria-hidden="true" />;
    case "link":
      return <Link2 size={size} aria-hidden="true" />;
    case "table":
      return <Table2 size={size} aria-hidden="true" />;
    case "chart":
      return <BarChart3 size={size} aria-hidden="true" />;
    case "diagnostics":
      return <LineChart size={size} aria-hidden="true" />;
    case "share":
      return <Share2 size={size} aria-hidden="true" />;
    case "download":
      return <Download size={size} aria-hidden="true" />;
    case "archive":
      return <Trash2 size={size} aria-hidden="true" />;
    case "sql":
      // Text glyph, matching the pre-existing Detailed View treatment.
      return <span aria-hidden="true" className="text-[11px] font-bold leading-none">SQL</span>;
    default:
      return null;
  }
}

/** The tooltip a control shows: the disabled reason wins when disabled, so the
 *  user is always told WHY rather than being left with a dead control. */
export function actionTitle(action: DatasetAction): string {
  return action.enabled ? action.tooltip : action.disabledReason || action.tooltip;
}

/** Accessible name; when disabled it carries the reason so screen-reader users
 *  receive the same explanation sighted users get from the tooltip. */
export function actionAccessibleName(action: DatasetAction): string {
  return action.enabled ? action.accessibleLabel : `${action.accessibleLabel} (unavailable: ${action.disabledReason})`;
}

/**
 * Detailed View control: compact, icon-first, but driven entirely by the shared
 * action object. Navigation actions render as links when enabled and as inert
 * buttons when disabled, so a disabled action cannot be followed.
 */
export function DatasetActionIconControl({
  action,
  onInvoke,
}: {
  action: DatasetAction;
  onInvoke: (action: DatasetAction) => void;
}) {
  const base = "inline-flex h-8 min-w-8 items-center justify-center rounded-md border px-2 transition";
  const tone = !action.enabled
    ? "cursor-not-allowed border-slate-200 bg-slate-50 text-slate-400"
    : action.destructive
      ? "border-red-200 bg-white text-red-700 hover:bg-red-50"
      : action.id === "open"
        ? "border-slate-950 bg-slate-950 text-white hover:bg-slate-800"
        : action.id === "sql-studio"
          ? "border-indigo-200 bg-indigo-50 text-indigo-800 hover:bg-indigo-100"
          : action.id === "share"
            ? "border-blue-200 bg-blue-50 text-blue-800 hover:bg-blue-100"
            : action.id === "model-diagnostics"
              ? "border-emerald-200 bg-emerald-50 text-emerald-800 hover:bg-emerald-100"
              : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50";

  if (action.navigateTo && action.enabled) {
    return (
      <Link
        to={action.navigateTo}
        title={actionTitle(action)}
        aria-label={actionAccessibleName(action)}
        data-dataset-action={action.id}
        data-action-enabled="true"
        className={`${base} ${tone}`}
      >
        <ActionIcon icon={action.icon} />
      </Link>
    );
  }

  return (
    <button
      type="button"
      title={actionTitle(action)}
      aria-label={actionAccessibleName(action)}
      aria-disabled={!action.enabled}
      disabled={!action.enabled}
      data-dataset-action={action.id}
      data-action-enabled={action.enabled ? "true" : "false"}
      data-disabled-reason={action.enabled ? undefined : action.disabledReason || undefined}
      onClick={() => action.enabled && onInvoke(action)}
      className={`${base} ${tone}`}
    >
      <ActionIcon icon={action.icon} />
    </button>
  );
}

/**
 * Card View primary control: icon PLUS a visible text label, so no capability in
 * Card View is conveyed by an icon alone.
 */
export function DatasetActionPrimaryControl({
  action,
  onInvoke,
}: {
  action: DatasetAction;
  onInvoke: (action: DatasetAction) => void;
}) {
  const base =
    "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-semibold transition";
  const tone = !action.enabled
    ? "cursor-not-allowed border-slate-200 bg-slate-50 text-slate-400"
    : action.id === "open"
      ? "border-slate-950 bg-slate-950 text-white hover:bg-slate-800"
      : action.id === "sql-studio"
        ? "border-indigo-200 bg-indigo-50 text-indigo-800 hover:bg-indigo-100"
        : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50";

  if (action.navigateTo && action.enabled) {
    return (
      <Link
        to={action.navigateTo}
        title={actionTitle(action)}
        aria-label={actionAccessibleName(action)}
        data-dataset-action={action.id}
        data-action-enabled="true"
        className={`${base} ${tone}`}
      >
        <ActionIcon icon={action.icon} />
        {action.label}
      </Link>
    );
  }

  return (
    <button
      type="button"
      title={actionTitle(action)}
      aria-label={actionAccessibleName(action)}
      aria-disabled={!action.enabled}
      disabled={!action.enabled}
      data-dataset-action={action.id}
      data-action-enabled={action.enabled ? "true" : "false"}
      data-disabled-reason={action.enabled ? undefined : action.disabledReason || undefined}
      onClick={() => action.enabled && onInvoke(action)}
      className={`${base} ${tone}`}
    >
      <ActionIcon icon={action.icon} />
      {action.label}
    </button>
  );
}

/**
 * Card View "More Actions" menu -- WAI-ARIA menu button pattern.
 *
 * Supports: keyboard opening (native button), Arrow Up/Down roving focus,
 * Home/End, Escape to close, focus return to the trigger, and outside-click
 * close. Destructive actions are separated by a rule AND carry a "Destructive"
 * text marker, so the separation is never conveyed by colour alone.
 */
export function DatasetActionMenu({
  actions,
  datasetName,
  onInvoke,
}: {
  actions: DatasetAction[];
  datasetName: string;
  onInvoke: (action: DatasetAction) => void;
}) {
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | HTMLAnchorElement | null>>([]);
  const menuId = useId();

  const close = (returnFocus: boolean) => {
    setOpen(false);
    if (returnFocus) triggerRef.current?.focus();
  };

  // Outside click closes without stealing focus back.
  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (menuRef.current?.contains(target) || triggerRef.current?.contains(target)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [open]);

  // Move DOM focus onto the active item so screen readers track the selection.
  useEffect(() => {
    if (!open) return;
    itemRefs.current[activeIndex]?.focus();
  }, [open, activeIndex]);

  const openAt = (index: number) => {
    setActiveIndex(index);
    setOpen(true);
  };

  const onTriggerKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openAt(0);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      openAt(actions.length - 1);
    }
  };

  const onMenuKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      close(true);
      return;
    }
    if (event.key === "Tab") {
      close(false);
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((current) => (current + 1) % actions.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((current) => (current - 1 + actions.length) % actions.length);
    } else if (event.key === "Home") {
      event.preventDefault();
      setActiveIndex(0);
    } else if (event.key === "End") {
      event.preventDefault();
      setActiveIndex(actions.length - 1);
    }
  };

  const invoke = (action: DatasetAction) => {
    if (!action.enabled) return;
    close(true);
    onInvoke(action);
  };

  const firstDestructive = actions.findIndex((action) => action.destructive);

  return (
    <div className="relative">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => (open ? close(false) : openAt(0))}
        onKeyDown={onTriggerKeyDown}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        aria-label={`More actions for ${datasetName}`}
        title="More actions"
        data-testid="dataset-more-actions-trigger"
        className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-50"
      >
        <MoreHorizontal size={15} aria-hidden="true" />
        More Actions
      </button>

      {open && (
        <div
          ref={menuRef}
          id={menuId}
          role="menu"
          aria-label={`More actions for ${datasetName}`}
          data-testid="dataset-more-actions-menu"
          onKeyDown={onMenuKeyDown}
          className="absolute right-0 z-30 mt-1 w-60 overflow-hidden rounded-lg border border-slate-200 bg-white py-1 shadow-lg"
        >
          {actions.map((action, index) => {
            const shared = {
              role: "menuitem" as const,
              tabIndex: index === activeIndex ? 0 : -1,
              title: actionTitle(action),
              "aria-label": actionAccessibleName(action),
              "data-dataset-action": action.id,
              "data-action-enabled": action.enabled ? "true" : "false",
              "data-disabled-reason": action.enabled ? undefined : action.disabledReason || undefined,
              className: `flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-semibold transition ${
                !action.enabled
                  ? "cursor-not-allowed text-slate-400"
                  : action.destructive
                    ? "text-red-700 hover:bg-red-50"
                    : "text-slate-700 hover:bg-slate-50"
              }`,
            };
            const body = (
              <>
                <ActionIcon icon={action.icon} size={14} />
                <span className="flex-1">{action.label}</span>
                {action.destructive && (
                  <span className="text-[10px] font-bold uppercase tracking-wide text-red-700">Destructive</span>
                )}
              </>
            );
            return (
              <div key={action.id}>
                {index === firstDestructive && firstDestructive > 0 && (
                  <div className="my-1 border-t border-slate-200" role="separator" />
                )}
                {action.navigateTo && action.enabled ? (
                  <Link
                    {...shared}
                    ref={(node) => {
                      itemRefs.current[index] = node;
                    }}
                    to={action.navigateTo}
                    onClick={() => close(false)}
                  >
                    {body}
                  </Link>
                ) : (
                  <button
                    {...shared}
                    ref={(node) => {
                      itemRefs.current[index] = node;
                    }}
                    type="button"
                    aria-disabled={!action.enabled}
                    disabled={!action.enabled}
                    onClick={() => invoke(action)}
                  >
                    {body}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
